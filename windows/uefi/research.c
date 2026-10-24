// SPDX-License-Identifier: GPL-2.0-only
#include "research.h"
#include "app_io.h"
#include "compat/compat.h"
#include "sha256.h"
#include <Guid/GlobalVariable.h>

EFI_STATUS GuSaveCapture(CHAR16 *File,const char *Name,const VOID *Data,UINTN Bytes) {
  EFI_STATUS status=GuSaveBlob(File,Data,Bytes);
  if(EFI_ERROR(status)) {
    GuLog("CAPTURE file=%s bytes=%zu status=%#llx verified=0\n",Name,(size_t)Bytes,(unsigned long long)status);
    return status;
  }
  UINT8 digest[32];char hex[65];static const char alphabet[]="0123456789abcdef";
  GuSha256(Data,Bytes,digest);
  for(UINTN i=0;i<32;i++){hex[i*2]=alphabet[digest[i]>>4];hex[i*2+1]=alphabet[digest[i]&15];}
  hex[64]=0;
  GuLog("CAPTURE file=%s bytes=%zu sha256=%s verified=1\n",Name,(size_t)Bytes,hex);
  return GuLogReady()?EFI_SUCCESS:EFI_DEVICE_ERROR;
}

/* Single aligned reads only, using the offsets already sampled by
 * diagnostics/peek/gpu_peek.c, plus VRAM size and known Falcon status words.
 * No sweeping BAR0, VRAM, indirect ports or instruction/data-memory windows. */
static const UINT32 Registers[]={
  0x00000000,0x00118128,0x00118234,0x00110100,0x001183a4,
  0x001fa824,0x001fa828,0x001fa7cc,0x009a0148,0x001fa7c4,
  0x00820000,0x00820040,0x00820078,0x0082007c,0x00820084,
  0x008200fc,0x00820224,0x0082038c,0x0082059c,
  0x008207d4,0x008207d8,0x008207dc,0x008207e0,0x008207e4,0x008207e8,0x008207ec,
  0x00823800,0x00823804,0x00823808,0x0082380c,0x00823810,
  0x00823814,0x00823818,0x0082381c,0x00823820,0x00823824,0x00823828,0x0082382c,
  0x00409664,0x00409668,0x00504204,
  0x00840100,0x008400f4,0x0084010c,0x00840118,0x00840040,0x00840044
};
typedef struct {UINT32 offset,value;UINT64 status;} REGISTER_RECORD;
typedef struct {
  UINT32 magic,version,count,stride;
  REGISTER_RECORD records[sizeof(Registers)/sizeof(Registers[0])];
} REGISTER_SNAPSHOT;
_Static_assert(sizeof(REGISTER_RECORD)==16,"register capture layout");

EFI_STATUS GuResearchRegisters(CHAR16 *File,const char *Name) {
  REGISTER_SNAPSHOT snapshot={0};
  snapshot.magic=0x31525547; /* GUR1, little endian */
  snapshot.version=1;snapshot.count=sizeof(Registers)/sizeof(Registers[0]);snapshot.stride=16;
  for(UINTN i=0;i<snapshot.count;i++) {
    REGISTER_RECORD *r=&snapshot.records[i];r->offset=Registers[i];r->value=~0U;
    r->status=EFI_UNSUPPORTED;
    if(Gu.pci && Gu.pci->Mem.Read && r->offset<=Gu.bar_size-4)
      r->status=Gu.pci->Mem.Read(Gu.pci,EfiPciIoWidthUint32,0,r->offset,1,&r->value);
    GuLog("REGISTER file=%s offset=%#x value=%#x status=%#llx\n",
      Name,r->offset,r->value,(unsigned long long)r->status);
  }
  return GuSaveCapture(File,Name,&snapshot,sizeof(snapshot));
}

typedef struct {CHAR16 *variable,*file;const char *name;} VARIABLE_SPEC;
static VOID CaptureVariable(EFI_RUNTIME_SERVICES *Runtime,CHAR16 *Variable,CHAR16 *File,const char *Name) {
  EFI_GUID global=EFI_GLOBAL_VARIABLE;UINTN bytes=0;UINT32 attributes=0;
  EFI_STATUS status=Runtime->GetVariable(Variable,&global,&attributes,&bytes,NULL);
  if(status!=EFI_BUFFER_TOO_SMALL || !bytes || bytes>65536) {
    GuLog("VARIABLE file=%s query_status=%#llx bytes=%zu captured=0\n",Name,(unsigned long long)status,(size_t)bytes);
    return;
  }
  VOID *data=GuAlloc(bytes);if(!data)return;
  UINTN allocated=bytes;
  status=Runtime->GetVariable(Variable,&global,&attributes,&bytes,data);
  GuLog("VARIABLE file=%s status=%#llx bytes=%zu attributes=%#x\n",Name,(unsigned long long)status,(size_t)bytes,attributes);
  if(!EFI_ERROR(status) && bytes && bytes<=allocated)GuSaveCapture(File,Name,data,bytes);
  GuFree(data);
}

VOID GuResearchPlatform(EFI_SYSTEM_TABLE *Table) {
  static const VARIABLE_SPEC vars[]={
    {L"SecureBoot",L"SECUREBOOT.BIN","SECUREBOOT.BIN"},
    {L"SetupMode",L"SETUPMODE.BIN","SETUPMODE.BIN"},
    {L"AuditMode",L"AUDITMODE.BIN","AUDITMODE.BIN"},
    {L"DeployedMode",L"DEPLOYEDMODE.BIN","DEPLOYEDMODE.BIN"},
    {L"BootCurrent",L"BOOTCURRENT.BIN","BOOTCURRENT.BIN"},
    {L"BootOrder",L"BOOTORDER.BIN","BOOTORDER.BIN"},
    {L"BootNext",L"BOOTNEXT.BIN","BOOTNEXT.BIN"},
    {L"OsIndicationsSupported",L"OSINDIC.BIN","OSINDIC.BIN"}
  };
  GuLog("PLATFORM UEFI_revision=%#x firmware_revision=%#x boot_services_revision=%#x\n",
    Table->Hdr.Revision,Table->FirmwareRevision,Table->BootServices->Hdr.Revision);
  if(Table->FirmwareVendor) {
    char vendor[129];UINTN n=0;
    while(n<128 && Table->FirmwareVendor[n]) {
      UINT16 c=Table->FirmwareVendor[n];vendor[n]=(char)(c>=32 && c<127?c:'?');n++;
    }
    vendor[n]=0;GuLog("PLATFORM firmware_vendor=%s\n",vendor);
  }
  EFI_RUNTIME_SERVICES *rt=Table->RuntimeServices;
  if(!rt || !rt->GetVariable)return;
  if(rt->GetTime) {
    EFI_TIME time={0};EFI_STATUS status=rt->GetTime(&time,NULL);
    GuLog("PLATFORM rtc_status=%#llx year=%u month=%u day=%u hour=%u minute=%u second=%u timezone=%d\n",
      (unsigned long long)status,time.Year,time.Month,time.Day,time.Hour,time.Minute,time.Second,time.TimeZone);
    if(!EFI_ERROR(status))GuSaveCapture(L"TIME.BIN","TIME.BIN",&time,sizeof(time));
  }
  for(UINTN i=0;i<sizeof(vars)/sizeof(vars[0]);i++)CaptureVariable(rt,vars[i].variable,vars[i].file,vars[i].name);
  EFI_GUID global=EFI_GLOBAL_VARIABLE;UINT16 order[32];UINTN bytes=sizeof(order);
  EFI_STATUS status=rt->GetVariable(L"BootOrder",&global,NULL,&bytes,order);
  if(!EFI_ERROR(status) && bytes<=sizeof(order) && !(bytes&1)) {
    static const char hex[]="0123456789ABCDEF";
    for(UINTN i=0;i<bytes/2;i++) {
      CHAR16 variable[]=L"Boot0000";char name[]="BOOT0000.BIN";CHAR16 file[]=L"BOOT0000.BIN";
      for(UINTN j=0;j<4;j++) {
        char c=hex[(order[i]>>(12-j*4))&15];variable[4+j]=(CHAR16)c;name[4+j]=c;file[4+j]=(CHAR16)c;
      }
      /* Duplicate boot numbers are malformed, and must not overwrite a prior capture. */
      BOOLEAN duplicate=FALSE;for(UINTN j=0;j<i;j++)if(order[j]==order[i])duplicate=TRUE;
      if(!duplicate)CaptureVariable(rt,variable,file,name);
    }
  }
}

VOID GuResearchPromRepeat(VOID *Buffer,const UINT8 FirstHash[32]) {
  EFI_STATUS status=EFI_UNSUPPORTED;
  if(Gu.pci && Gu.pci->Mem.Read) {
    status=EFI_SUCCESS;
    for(UINTN done=0;!EFI_ERROR(status) && done<1048576;done+=1024)
      status=Gu.pci->Mem.Read(Gu.pci,EfiPciIoWidthUint32,0,0x300000+done,256,(UINT8 *)Buffer+done);
  }
  GuLog("PROM repeat read status=%#llx\n",(unsigned long long)status);
  if(!EFI_ERROR(status)) {
    UINT8 second[32];GuSha256(Buffer,1048576,second);
    GuLog("PROM repeat identical=%u\n",!memcmp(FirstHash,second,32));
    GuSaveCapture(L"PROM2.BIN","PROM2.BIN",Buffer,1048576);
  }
}
