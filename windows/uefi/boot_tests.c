// SPDX-License-Identifier: GPL-2.0-only
#include "boot_tests.h"
#include "compat/compat.h"
#include "checks.h"
#include "app_io.h"
#include "research.h"
#include "ownership.h"
#include "vendor/vbios_610.h"
#include "vendor/gfw_eval.h"
#include <Protocol/SimpleFileSystem.h>

VOID GuBootTestPci(const UINT32 Config[64]) {
  GU_CAPS caps={0};BOOLEAN pass=GuCheckPciState(Config,&caps);
  GuLog("TEST PCI_STATE pass=%u PM=%#x PCIe=%#x MSI=%#x MSIX=%#x writes=0\n",
    pass,caps.pm,caps.pcie,caps.msi,caps.msix);
  GuLogText("PCI_STATE checks capability-chain bounds, D0, FLR support, BME=0 and interrupt-disable state. No reset is issued.\n");
}

VOID GuBootTestFirmware(const VOID *Data,UINTN Bytes,BOOLEAN Prom) {
  struct gpu_unlock_fwsec fw={0};
  int result=gpu_unlock_vbios_fwsec(Data,Bytes,&fw);
  GuLog("TEST %s_FWSEC_PARSE pass=%u parser_result=%d execution=0\n",Prom?"PROM":"ROM",!result,result);
  if(result)return;
  GuLog("FWSEC source=%s engine=%#x ucode=%u imem=%#x dmem=%#x signatures=%u versions=%#x\n",
    Prom?"PROM":"ROM",fw.engine_mask,fw.ucode_id,fw.imem_size,fw.dmem_size,fw.sig_count,fw.sig_versions);
  if(fw.image_off>Bytes || fw.image_size>Bytes-fw.image_off || fw.sig_off>Bytes || fw.sig_bytes>Bytes-fw.sig_off)return;
  GuSaveCapture(Prom?L"P_FWDESC.BIN":L"R_FWDESC.BIN",Prom?"P_FWDESC.BIN":"R_FWDESC.BIN",&fw,sizeof(fw));
  GuSaveCapture(Prom?L"P_FWSEC.BIN":L"R_FWSEC.BIN",Prom?"P_FWSEC.BIN":"R_FWSEC.BIN",(const UINT8 *)Data+fw.image_off,fw.image_size);
  if(fw.sig_bytes)GuSaveCapture(Prom?L"P_FWSIG.BIN":L"R_FWSIG.BIN",Prom?"P_FWSIG.BIN":"R_FWSIG.BIN",(const UINT8 *)Data+fw.sig_off,fw.sig_bytes);
}

VOID GuBootTestReadiness(VOID) {
  UINT32 values[3]={~0U,~0U,~0U};
  const UINT32 offsets[]={GU_GFW_PLM_OFFSET,GU_GFW_BOOT_OFFSET,GU_GFW_CPUCTL_OFFSET};
  EFI_STATUS status=EFI_UNSUPPORTED;
  if(Gu.pci && Gu.pci->Mem.Read) {
    status=EFI_SUCCESS;
    for(UINTN i=0;i<3 && !EFI_ERROR(status);i++)
      status=Gu.pci->Mem.Read(Gu.pci,EfiPciIoWidthUint32,0,offsets[i],1,&values[i]);
  }
  struct gpu_unlock_gfw_sample sample={.config_ok=!EFI_ERROR(status),.plm=values[0],.boot=values[1],.cpuctl=values[2]};
  int result=gpu_unlock_gfw_assess(&sample);
  GuLog("TEST GPU_BOOT_READY pass=%u transport=%#llx assess=%d PLM=%#x boot=%#x CPUCTL=%#x execution=0\n",
    !result,(unsigned long long)status,result,values[0],values[1],values[2]);
}

VOID GuBootTestAssets(VOID) {
  EFI_STATUS status=GuLoadAssets();
  GuLog("TEST PINNED_ASSETS pass=%u status=%#llx firmware_execution=0 DMA=0\n",!EFI_ERROR(status),(unsigned long long)status);
  GuReleaseAssets();
}

VOID GuBootTestEnvironment(EFI_SYSTEM_TABLE *Table) {
  EFI_BOOT_SERVICES *bs=Table->BootServices;
  if(bs->RaiseTPL && bs->RestoreTPL && bs->ProtocolsPerHandle && bs->OpenProtocolInformation && bs->FreePool) {
    GU_RELEASE_OWNER owner={0};EFI_STATUS status=GuFindReleaseOwner(Table,&owner,TRUE);
    GuLog("TEST GPU_FIRMWARE_OWNER pass=%u status=%#llx GOP_children=%zu driver_disconnected=0\n",
      !EFI_ERROR(status),(unsigned long long)status,(size_t)owner.child_count);
  } else GuLogText("TEST GPU_FIRMWARE_OWNER unavailable=1 driver_disconnected=0\n");
  EFI_GUID fs_guid=EFI_SIMPLE_FILE_SYSTEM_PROTOCOL_GUID;
  EFI_HANDLE *handles=NULL;UINTN count=0,candidates=0,valid=0;
  EFI_STATUS status=bs->LocateHandleBuffer(ByProtocol,&fs_guid,NULL,&count,&handles);
  if(!EFI_ERROR(status) && (!handles || count>64))status=EFI_COMPROMISED_DATA;
  for(UINTN i=0;!EFI_ERROR(status) && i<count;i++) {
    EFI_SIMPLE_FILE_SYSTEM_PROTOCOL *fs=NULL;EFI_FILE_PROTOCOL *root=NULL,*file=NULL;
    EFI_STATUS step=bs->HandleProtocol(handles[i],&fs_guid,(VOID **)&fs);
    if(EFI_ERROR(step) || !fs)continue;
    step=fs->OpenVolume(fs,&root);if(EFI_ERROR(step) || !root)continue;
    step=root->Open(root,&file,L"\\EFI\\Microsoft\\Boot\\bootmgfw.efi",EFI_FILE_MODE_READ,0);
    if(!EFI_ERROR(step) && file) {
      candidates++;UINT8 header[512];UINTN bytes=sizeof(header);
      step=file->Read(file,&bytes,header);
      BOOLEAN good=FALSE;
      if(!EFI_ERROR(step) && bytes==sizeof(header) && header[0]=='M' && header[1]=='Z') {
        UINT32 pe=(UINT32)header[60]|((UINT32)header[61]<<8)|((UINT32)header[62]<<16)|((UINT32)header[63]<<24);
        if(pe<=sizeof(header)-6 && !memcmp(header+pe,"PE\0\0",4) && header[pe+4]==0x64 && header[pe+5]==0x86)good=TRUE;
      }
      if(good)valid++;
      EFI_STATUS closed=file->Close(file);
      GuLog("WINDOWS_BOOT_HEADER candidate=%zu x64_PE=%u read_status=%#llx close_status=%#llx image_loaded=0\n",
        (size_t)candidates,good,(unsigned long long)step,(unsigned long long)closed);
    }
    root->Close(root);
  }
  GuFree(handles);
  GuLog("TEST WINDOWS_BOOT_FILE pass=%u candidates=%zu x64_headers=%zu status=%#llx LoadImage=0 StartImage=0\n",
    candidates==1 && valid==1 && !EFI_ERROR(status),(size_t)candidates,(size_t)valid,(unsigned long long)status);
}
