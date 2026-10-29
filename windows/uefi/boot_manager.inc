/* SPDX-License-Identifier: GPL-2.0-only */
/* Exact Windows-file preflight, inspired by JustAResearcher/gpu-unlock-ada
 * PR #104 (26fdc047). No board geometry or SecureBoot-off policy is imported.
 * Included by handoff.inc so both public and later local adapters can retain
 * their own transaction, display-release and recovery code. */
#include <Protocol/LoadedImage.h>
#include <Protocol/SimpleFileSystem.h>
#include <Guid/FileInfo.h>
#include "sha256.h"
#include "boot_profile.h"
#if GU_WINDOWS_BOOTMGR_BYTES < 1048576 || GU_WINDOWS_BOOTMGR_BYTES > 8388608
#error "A reviewed private boot-manager size of 1-8 MiB is required."
#endif
static EFI_GUID FsGuid=EFI_SIMPLE_FILE_SYSTEM_PROTOCOL_GUID,LoadedGuid=EFI_LOADED_IMAGE_PROTOCOL_GUID;
static const EFI_GUID WindowsPartition=GU_WINDOWS_PARTITION_INITIALIZER;
static const CHAR16 WindowsPath[]=L"\\EFI\\Microsoft\\Boot\\bootmgfw.efi";
static EFI_HANDLE WindowsImage,WindowsVolume;
static EFI_DEVICE_PATH_PROTOCOL *WindowsDevicePath;

/* The caller uses this only before release/mutation, or after proven cleanup.
 * A policy-denied LoadImage may still return a handle. Attempt its unload once,
 * including on preflight failure/cancel; never StartImage on that handle. */
static EFI_STATUS UnloadWindows(VOID) {
  EFI_HANDLE image=WindowsImage;WindowsImage=NULL;
  EFI_STATUS s=image?Gu.bs->UnloadImage(image):EFI_SUCCESS;
  GuFree(WindowsDevicePath);WindowsDevicePath=NULL;WindowsVolume=NULL;
  return s;
}
static EFI_STATUS InspectWindowsVolume(EFI_HANDLE Volume,BOOLEAN *Match,UINTN *Bytes,EFI_DEVICE_PATH_PROTOCOL **Path) {
  EFI_DEVICE_PATH_PROTOCOL *base=NULL;
  *Match=FALSE;*Bytes=0;if(Path)*Path=NULL;
  EFI_STATUS s=Gu.bs->HandleProtocol(Volume,&PathGuid,(VOID **)&base);
  if(EFI_ERROR(s)||!base)return EFI_UNSUPPORTED;
  UINTN off=0,hd=0;BOOLEAN usb=FALSE,matched=FALSE;
  for(UINTN i=0;i<128 && off<=4092;i++) {
    EFI_DEVICE_PATH_PROTOCOL *node=(VOID *)((UINT8 *)base+off);
    UINTN n=node->Length[0]+((UINTN)node->Length[1]<<8);
    if(n<4||n>4096-off)return EFI_COMPROMISED_DATA;
    if(node->Type==END_DEVICE_PATH_TYPE) {
      if(node->SubType!=END_ENTIRE_DEVICE_PATH_SUBTYPE||n!=4)return EFI_UNSUPPORTED;
      *Match=matched&&!usb;*Bytes=off+4;if(Path)*Path=base;return EFI_SUCCESS;
    }
    if(node->Type==MESSAGING_DEVICE_PATH &&
       (node->SubType==MSG_USB_DP||node->SubType==MSG_USB_CLASS_DP||node->SubType==MSG_USB_WWID_DP))usb=TRUE;
    if(node->Type==MEDIA_DEVICE_PATH&&node->SubType==MEDIA_HARDDRIVE_DP) {
      if(n!=sizeof(HARDDRIVE_DEVICE_PATH)||++hd!=1)return EFI_COMPROMISED_DATA;
      const HARDDRIVE_DEVICE_PATH *disk=(const VOID *)node;
      matched=disk->MBRType==2&&disk->SignatureType==2&&!memcmp(disk->Signature,&WindowsPartition,16);
    }
    off+=n;
  }
  return EFI_COMPROMISED_DATA;
}
static EFI_STATUS MakeWindowsPath(UINTN BaseBytes) {
  EFI_DEVICE_PATH_PROTOCOL *base=NULL;
  BOOLEAN match=FALSE;UINTN checked=0;
  EFI_STATUS s=InspectWindowsVolume(WindowsVolume,&match,&checked,&base);
  if(EFI_ERROR(s)||!match||checked!=BaseBytes)return EFI_COMPROMISED_DATA;
  UINTN off=BaseBytes-4,node=4+sizeof(WindowsPath),total=off+node+4;
  UINT8 *b=GuAlloc(total);if(!b)return EFI_OUT_OF_RESOURCES;
  memcpy(b,base,off);b[off]=MEDIA_DEVICE_PATH;b[off+1]=MEDIA_FILEPATH_DP;
  b[off+2]=(UINT8)node;b[off+3]=(UINT8)(node>>8);memcpy(b+off+4,WindowsPath,sizeof(WindowsPath));
  b[off+node]=END_DEVICE_PATH_TYPE;b[off+node+1]=END_ENTIRE_DEVICE_PATH_SUBTYPE;
  b[off+node+2]=4;b[off+node+3]=0;
  WindowsDevicePath=(VOID *)b;return EFI_SUCCESS;
}
static EFI_STATUS ReadWindowsFile(VOID **Data) {
  EFI_SIMPLE_FILE_SYSTEM_PROTOCOL *fs=NULL;EFI_FILE_PROTOCOL *root=NULL,*file=NULL;
  *Data=NULL;
  EFI_STATUS s=Gu.bs->HandleProtocol(WindowsVolume,&FsGuid,(VOID **)&fs);
  if(EFI_ERROR(s)||!fs)return EFI_UNSUPPORTED;
  s=fs->OpenVolume(fs,&root);
  if(EFI_ERROR(s)||!root)return EFI_DEVICE_ERROR;
  s=root->Open(root,&file,(CHAR16 *)WindowsPath,EFI_FILE_MODE_READ,0);
  if(!EFI_ERROR(s)&&!file)s=EFI_DEVICE_ERROR;
  VOID *data=NULL;
  if(!EFI_ERROR(s)) {
    EFI_GUID info_guid=EFI_FILE_INFO_ID;
    UINT64 info_words[128];UINTN info_bytes=sizeof(info_words);
    s=file->GetInfo(file,&info_guid,&info_bytes,info_words);
    EFI_FILE_INFO *info=(VOID *)info_words;
    if(!EFI_ERROR(s)&&(info_bytes<SIZE_OF_EFI_FILE_INFO+sizeof(CHAR16)||info_bytes>sizeof(info_words)||
       info->Size<SIZE_OF_EFI_FILE_INFO+sizeof(CHAR16)||info->Size>info_bytes||
       info->FileSize!=GU_WINDOWS_BOOTMGR_BYTES||(info->Attribute&EFI_FILE_DIRECTORY)))s=EFI_COMPROMISED_DATA;
    if(!EFI_ERROR(s)){data=GuAlloc(GU_WINDOWS_BOOTMGR_BYTES);if(!data)s=EFI_OUT_OF_RESOURCES;}
    for(UINTN at=0;!EFI_ERROR(s)&&at<GU_WINDOWS_BOOTMGR_BYTES;) {
      UINTN n=GU_WINDOWS_BOOTMGR_BYTES-at;if(n>1048576)n=1048576;UINTN wanted=n;
      s=file->Read(file,&n,(UINT8 *)data+at);
      if(!EFI_ERROR(s)&&n!=wanted)s=EFI_DEVICE_ERROR;
      if(!EFI_ERROR(s))at+=n;
    }
    if(!EFI_ERROR(s)) {
      UINT8 tail;UINTN n=1;s=file->Read(file,&n,&tail);
      if(!EFI_ERROR(s)&&n!=0)s=EFI_COMPROMISED_DATA;
    }
  }
  if(file){EFI_STATUS x=file->Close(file);if(!EFI_ERROR(s))s=x;}
  EFI_STATUS x=root->Close(root);if(!EFI_ERROR(s))s=x;
  if(!EFI_ERROR(s)&&(((UINT8 *)data)[0]!='M'||((UINT8 *)data)[1]!='Z'||
     !GuHashMatches(data,GU_WINDOWS_BOOTMGR_BYTES,GU_WINDOWS_BOOTMGR_SHA256)))s=EFI_CRC_ERROR;
  if(EFI_ERROR(s)){GuFree(data);return s;}
  *Data=data;return EFI_SUCCESS;
}
static EFI_STATUS PreloadWindows(VOID) {
  if(WindowsImage||WindowsDevicePath||WindowsVolume)return EFI_ALREADY_STARTED;
  EFI_LOADED_IMAGE_PROTOCOL *self=NULL;
  EFI_STATUS s=Gu.bs->HandleProtocol(Gu.image,&LoadedGuid,(VOID **)&self);
  if(EFI_ERROR(s)||!self||!self->DeviceHandle)return EFI_UNSUPPORTED;
  EFI_HANDLE own=self->DeviceHandle,*h=NULL;UINTN n=0,found=0,path_bytes=0;
  s=Gu.bs->LocateHandleBuffer(ByProtocol,&FsGuid,NULL,&n,&h);
  if(!EFI_ERROR(s)&&(!h||n==0||n>256))s=EFI_COMPROMISED_DATA;
  for(UINTN i=0;!EFI_ERROR(s)&&i<n;i++) {
    BOOLEAN match=FALSE;UINTN bytes=0;
    s=InspectWindowsVolume(h[i],&match,&bytes,NULL);
    if(!EFI_ERROR(s)&&match) {
      if(h[i]==own){s=EFI_ACCESS_DENIED;break;}
      found++;WindowsVolume=h[i];path_bytes=bytes;
    }
  }
  GuFree(h);
  if(!EFI_ERROR(s)&&found!=1)s=found?EFI_NO_MAPPING:EFI_NOT_FOUND;
  VOID *data=NULL;
  if(!EFI_ERROR(s))s=ReadWindowsFile(&data);
  if(!EFI_ERROR(s))s=MakeWindowsPath(path_bytes);
  if(!EFI_ERROR(s)) {
    /* Firmware still authenticates this image. A matching pin never overrides
     * LoadImage policy, signature or revocation failures. Keep its full path. */
    s=Gu.bs->LoadImage(FALSE,Gu.image,WindowsDevicePath,data,GU_WINDOWS_BOOTMGR_BYTES,&WindowsImage);
    if(!EFI_ERROR(s)&&!WindowsImage)s=EFI_DEVICE_ERROR;
  }
  GuFree(data);
  if(!EFI_ERROR(s)) {
    EFI_LOADED_IMAGE_PROTOCOL *li=NULL;
    s=Gu.bs->HandleProtocol(WindowsImage,&LoadedGuid,(VOID **)&li);
    if(!EFI_ERROR(s)&&(!li||li->DeviceHandle!=WindowsVolume||li->ImageCodeType!=EfiLoaderCode))s=EFI_COMPROMISED_DATA;
  }
  GuLog("Windows preload status=%#llx matching_ESP=%zu size_and_SHA256_required=1\n",
    (unsigned long long)s,(size_t)found);
  if(!EFI_ERROR(s)&&!GuLogReady())s=EFI_DEVICE_ERROR;
  return s;
}
