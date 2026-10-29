// SPDX-License-Identifier: GPL-2.0-only
/* Actual preload and Secure Boot admission code, with synthetic public bytes
 * and simulated EFI services. No Windows binary, ESP or GPU access. */
#include <Uefi.h>
#include <Protocol/DevicePath.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../uefi/security.h"
static struct {EFI_BOOT_SERVICES *bs;EFI_HANDLE image;} Gu;
static unsigned live,allocs,loads,unloads,starts,opens,closed_files,closed_roots;
static unsigned reads,load_bytes,tests;
static int mode,secure_value;
static BOOLEAN log_ready;
static EFI_GUID PathGuid=EFI_DEVICE_PATH_PROTOCOL_GUID;
#define CHECK(x) do {if(!(x)){fprintf(stderr,"boot-manager mode=%d line=%d: %s\n",mode,__LINE__,#x);exit(1);}} while(0)
enum {GOOD,BAD_HASH,SMALL,LARGE,SHORT,ZERO_READ,TAIL,DIRECTORY,INFO_SHORT,INFO_LONG,INFO_SIZE,
      INFO_FAIL,FILE_CLOSE_FAIL,ROOT_CLOSE_FAIL,OPEN_FAIL,ROOT_FAIL,BUFFER_OOM,PATH_OOM,
      NO_ESP,WRONG_ESP,DUPLICATE_ESP,OWN_ESP,BAD_PATH,NO_END,USB_ESP,WRONG_DEVICE,
      WRONG_TYPE,LOAD_POLICY,LOAD_ACCESS,LOAD_FAIL,NULL_IMAGE,LOADED_PROTOCOL_FAIL,
      LOG_FAIL,ENUM_FAIL,ENUM_COUNT,UNLOAD_FAIL,MODE_COUNT};
static VOID *GuAlloc(size_t size) {
  allocs++;
  if((mode==BUFFER_OOM&&allocs==1)||(mode==PATH_OOM&&allocs==2))return NULL;
  VOID *p=calloc(1,size);CHECK(p);live++;return p;
}
static VOID GuFree(VOID *p){if(p){CHECK(live);live--;free(p);}}
static VOID GuLog(const char *format,...){(void)format;}
static BOOLEAN GuLogReady(VOID){return log_ready;}
#include "../uefi/boot_manager.inc"

static EFI_BOOT_SERVICES bs;
static EFI_RUNTIME_SERVICES rs;
static EFI_LOADED_IMAGE_PROTOCOL self_image,win_image;
static EFI_SIMPLE_FILE_SYSTEM_PROTOCOL fs;
static EFI_FILE_PROTOCOL root,file;
static UINT8 disk_path[46],other_path[46],usb_path[52];
static UINT8 *storage;
static UINTN position;
#define SELF ((EFI_HANDLE)(UINTN)1)
#define OWN ((EFI_HANDLE)(UINTN)2)
#define WIN ((EFI_HANDLE)(UINTN)3)
#define OTHER ((EFI_HANDLE)(UINTN)4)
#define IMAGE ((EFI_HANDLE)(UINTN)5)
static EFI_STATUS EFIAPI FreePool(VOID *p){GuFree(p);return EFI_SUCCESS;}
static EFI_STATUS EFIAPI Locate(EFI_LOCATE_SEARCH_TYPE type,EFI_GUID *guid,VOID *key,UINTN *count,EFI_HANDLE **handles) {
  CHECK(type==ByProtocol&&!key&&!memcmp(guid,&FsGuid,16));
  *handles=calloc(3,sizeof(**handles));CHECK(*handles);live++;
  (*handles)[0]=OWN;(*handles)[1]=WIN;(*handles)[2]=OTHER;
  *count=mode==ENUM_COUNT?257:mode==DUPLICATE_ESP?3:mode==NO_ESP?1:2;
  return mode==ENUM_FAIL?EFI_DEVICE_ERROR:EFI_SUCCESS;
}
static EFI_STATUS EFIAPI Handle(EFI_HANDLE handle,EFI_GUID *guid,VOID **out) {
  *out=NULL;
  if(!memcmp(guid,&LoadedGuid,16)) {
    if(handle==SELF)*out=&self_image;
    if(handle==IMAGE&&mode!=LOADED_PROTOCOL_FAIL)*out=&win_image;
  } else if(!memcmp(guid,&PathGuid,16)) {
    if(handle==OWN)*out=mode==OWN_ESP?disk_path:other_path;
    if(handle==WIN||handle==OTHER)*out=mode==USB_ESP?usb_path:disk_path;
  } else if(!memcmp(guid,&FsGuid,16)&&handle==WIN)*out=&fs;
  return *out?EFI_SUCCESS:EFI_UNSUPPORTED;
}
static EFI_STATUS EFIAPI Volume(EFI_SIMPLE_FILE_SYSTEM_PROTOCOL *p,EFI_FILE_PROTOCOL **out) {
  CHECK(p==&fs);*out=mode==ROOT_FAIL?NULL:&root;return mode==ROOT_FAIL?EFI_DEVICE_ERROR:EFI_SUCCESS;
}
static EFI_STATUS EFIAPI Open(EFI_FILE_PROTOCOL *p,EFI_FILE_PROTOCOL **out,CHAR16 *name,UINT64 flags,UINT64 attrs) {
  CHECK(p==&root&&flags==EFI_FILE_MODE_READ&&!attrs&&!memcmp(name,WindowsPath,sizeof(WindowsPath)));
  opens++;position=0;*out=mode==OPEN_FAIL?NULL:&file;
  return mode==OPEN_FAIL?EFI_NOT_FOUND:EFI_SUCCESS;
}
static EFI_STATUS EFIAPI Info(EFI_FILE_PROTOCOL *p,EFI_GUID *guid,UINTN *n,VOID *data) {
  EFI_GUID expected=EFI_FILE_INFO_ID;CHECK(p==&file&&!memcmp(guid,&expected,16));
  CHECK(*n>=sizeof(EFI_FILE_INFO));memset(data,0,*n);
  EFI_FILE_INFO *info=data;info->Size=SIZE_OF_EFI_FILE_INFO+2;
  info->FileSize=GU_WINDOWS_BOOTMGR_BYTES+(mode==LARGE?1:0)-(mode==SMALL?1:0);
  info->Attribute=mode==DIRECTORY?EFI_FILE_DIRECTORY:0;
  *n=mode==INFO_SHORT?1:mode==INFO_LONG?2048:(UINTN)info->Size;
  if(mode==INFO_SIZE)info->Size=4096;
  return mode==INFO_FAIL?EFI_DEVICE_ERROR:EFI_SUCCESS;
}
static EFI_STATUS EFIAPI Read(EFI_FILE_PROTOCOL *p,UINTN *n,VOID *data) {
  CHECK(p==&file&&*n<=1048576);reads++;
  UINTN available=GU_WINDOWS_BOOTMGR_BYTES-position;
  if(!available){*n=mode==TAIL?1:0;if(*n)*(UINT8 *)data=0x42;return EFI_SUCCESS;}
  if(*n>available)*n=available;
  if(mode==SHORT)(*n)--;
  if(mode==ZERO_READ)*n=0;
  memcpy(data,storage+position,*n);position+=*n;return EFI_SUCCESS;
}
static EFI_STATUS EFIAPI Close(EFI_FILE_PROTOCOL *p) {
  CHECK(p==&root||p==&file);
  if(p==&file){closed_files++;return mode==FILE_CLOSE_FAIL?EFI_DEVICE_ERROR:EFI_SUCCESS;}
  closed_roots++;return mode==ROOT_CLOSE_FAIL?EFI_DEVICE_ERROR:EFI_SUCCESS;
}
static EFI_STATUS EFIAPI Load(BOOLEAN policy,EFI_HANDLE parent,EFI_DEVICE_PATH_PROTOCOL *path,
                              VOID *bytes,UINTN size,EFI_HANDLE *out) {
  CHECK(!policy&&parent==SELF&&bytes&&path&&size==GU_WINDOWS_BOOTMGR_BYTES);
  CHECK(!memcmp(bytes,storage,size));CHECK(GuHashMatches(bytes,size,GU_WINDOWS_BOOTMGR_SHA256));
  CHECK(!memcmp(path,disk_path,42));
  const UINT8 *node=(const VOID *)((const UINT8 *)path+42);
  CHECK(node[0]==MEDIA_DEVICE_PATH&&node[1]==MEDIA_FILEPATH_DP);
  CHECK(!memcmp(node+4,WindowsPath,sizeof(WindowsPath)));
  node+=4+sizeof(WindowsPath);CHECK(node[0]==127&&node[1]==255&&node[2]==4&&node[3]==0);
  loads++;load_bytes=(unsigned)size;
  *out=(mode==LOAD_ACCESS||mode==LOAD_FAIL||mode==NULL_IMAGE)?NULL:IMAGE;
  if(mode==LOAD_POLICY)return EFI_SECURITY_VIOLATION;
  if(mode==LOAD_ACCESS)return EFI_ACCESS_DENIED;
  if(mode==LOAD_FAIL)return EFI_LOAD_ERROR;
  return EFI_SUCCESS;
}
static EFI_STATUS EFIAPI Unload(EFI_HANDLE image){CHECK(image==IMAGE);unloads++;return mode==UNLOAD_FAIL?EFI_DEVICE_ERROR:EFI_SUCCESS;}
static EFI_STATUS EFIAPI Start(EFI_HANDLE image,UINTN *n,CHAR16 **data){(void)image;(void)n;(void)data;starts++;return EFI_ABORTED;}
static EFI_STATUS EFIAPI Variable(CHAR16 *name,EFI_GUID *guid,UINT32 *attrs,UINTN *n,VOID *data) {
  (void)name;(void)guid;CHECK(!attrs&&*n==1);*n=secure_value==3?2:1;*(UINT8 *)data=(UINT8)secure_value;
  return secure_value==4?EFI_NOT_FOUND:EFI_SUCCESS;
}
static VOID Setup(VOID) {
  CHECK(live==0);allocs=loads=unloads=starts=opens=reads=load_bytes=closed_files=closed_roots=0;
  WindowsImage=WindowsVolume=NULL;WindowsDevicePath=NULL;log_ready=mode!=LOG_FAIL;
  memset(&bs,0,sizeof(bs));memset(&rs,0,sizeof(rs));memset(&self_image,0,sizeof(self_image));memset(&win_image,0,sizeof(win_image));
  bs.HandleProtocol=Handle;bs.LocateHandleBuffer=Locate;bs.FreePool=FreePool;
  bs.LoadImage=Load;bs.UnloadImage=Unload;bs.StartImage=Start;rs.GetVariable=Variable;
  Gu.bs=&bs;Gu.image=SELF;self_image.DeviceHandle=OWN;
  win_image.DeviceHandle=mode==WRONG_DEVICE?OTHER:WIN;
  win_image.ImageCodeType=mode==WRONG_TYPE?EfiBootServicesCode:EfiLoaderCode;
  memset(&fs,0,sizeof(fs));memset(&root,0,sizeof(root));memset(&file,0,sizeof(file));
  fs.OpenVolume=Volume;root.Open=Open;root.Close=Close;
  file.GetInfo=Info;file.Read=Read;file.Close=Close;
  memset(disk_path,0,sizeof(disk_path));HARDDRIVE_DEVICE_PATH *hd=(VOID *)disk_path;
  hd->Header.Type=MEDIA_DEVICE_PATH;hd->Header.SubType=MEDIA_HARDDRIVE_DP;hd->Header.Length[0]=42;
  /* Deliberately unlike PR104's partition1/LBA2048/204800-sector geometry. */
  hd->PartitionNumber=3;hd->PartitionStart=12345;hd->PartitionSize=345678;
  hd->MBRType=hd->SignatureType=2;memcpy(hd->Signature,&WindowsPartition,16);
  disk_path[42]=127;disk_path[43]=255;disk_path[44]=4;
  memcpy(other_path,disk_path,sizeof(disk_path));other_path[24]^=1;
  if(mode==WRONG_ESP)disk_path[24]^=1;
  if(mode==BAD_PATH)disk_path[2]=0;
  if(mode==NO_END){disk_path[42]=1;disk_path[44]=0;}
  memset(usb_path,0,sizeof(usb_path));usb_path[0]=3;usb_path[1]=5;usb_path[2]=6;
  memcpy(usb_path+6,disk_path,sizeof(disk_path));
  for(UINTN i=0;i<GU_WINDOWS_BOOTMGR_BYTES;i++)storage[i]=(UINT8)(i*17+31);
  storage[0]='M';storage[1]='Z';if(mode==BAD_HASH)storage[100]^=1;
}
int main(VOID) {
  storage=malloc(GU_WINDOWS_BOOTMGR_BYTES);CHECK(storage);
  for(secure_value=0;secure_value<=1;secure_value++) {
    for(mode=GOOD;mode<MODE_COUNT;mode++) {
      Setup();UINT8 secure=0xff;CHECK(GuReadSecureBoot(&rs,&secure)==EFI_SUCCESS&&secure==secure_value);
      EFI_STATUS s=PreloadWindows();tests++;
      BOOLEAN success=mode==GOOD||mode==UNLOAD_FAIL;
      CHECK((s==EFI_SUCCESS)==success);
      if(success){CHECK(loads==1&&load_bytes==GU_WINDOWS_BOOTMGR_BYTES);CHECK(PreloadWindows()==EFI_ALREADY_STARTED);}
      if(mode==BAD_HASH||mode==SMALL||mode==LARGE||mode==SHORT||mode==ZERO_READ||mode==TAIL)CHECK(loads==0);
      if(mode==LOAD_POLICY){CHECK(s==EFI_SECURITY_VIOLATION&&WindowsImage==IMAGE);}
      if(opens&&mode!=OPEN_FAIL)CHECK(closed_files==1);
      if(opens)CHECK(closed_roots==1);
      CHECK(starts==0);
      BOOLEAN had_image=WindowsImage!=NULL;
      EFI_STATUS cleanup=UnloadWindows();CHECK((cleanup==EFI_SUCCESS)==(mode!=UNLOAD_FAIL));
      CHECK(unloads==(unsigned)had_image&&live==0&&!WindowsImage&&!WindowsVolume&&!WindowsDevicePath);
      CHECK(UnloadWindows()==EFI_SUCCESS&&unloads==(unsigned)had_image);
    }
  }
  mode=GOOD;
  for(secure_value=2;secure_value<=4;secure_value++) {
    Setup();UINT8 secure;CHECK(EFI_ERROR(GuReadSecureBoot(&rs,&secure)));CHECK(!loads&&!starts);tests++;
  }
  free(storage);printf("Windows boot-manager: %u scenarios passed; exact buffer/path, pins, SecureBoot 0/1, policy denial and cleanup; EFI services simulated.\n",tests);
  return 0;
}
