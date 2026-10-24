// SPDX-License-Identifier: GPL-2.0-only
#include "app_io.h"
#include "sha256.h"
#include <IndustryStandard/Acpi.h>
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

EFI_STATUS EFIAPI EfiMain(EFI_HANDLE,EFI_SYSTEM_TABLE *);
GU_PLATFORM Gu;
BOOLEAN GuScreenDetached;
static EFI_BOOT_SERVICES bs;
static EFI_RUNTIME_SERVICES rt;
static EFI_PCI_IO_PROTOCOL pci;
static UINT32 config[64];
static UINT8 rom[512];
static EFI_GUID test_pci_guid=EFI_PCI_IO_PROTOCOL_GUID;
static int scenario, saved, complete, writes, extra_saved;
static BOOLEAN NameIs(const CHAR16 *a,const CHAR16 *b){while(*a && *a==*b){a++;b++;}return *a==*b;}

VOID GuInit(EFI_BOOT_SERVICES *b,EFI_PCI_IO_PROTOCOL *p){memset(&Gu,0,sizeof(Gu));Gu.bs=b;Gu.pci=p;}
VOID *GuAlloc(size_t n){return calloc(1,n);}
VOID GuFree(VOID *p){free(p);}
VOID GuConsole(const char *text){(void)text;}
VOID GuLogText(const char *text){if(strstr(text,"PROFILE complete=1"))complete++;}
VOID GuLog(const char *format,...){(void)format;}
BOOLEAN GuLogReady(VOID){return TRUE;}
EFI_STATUS GuIoOpen(EFI_HANDLE i,EFI_SYSTEM_TABLE *t){(void)i;(void)t;return EFI_SUCCESS;}
EFI_STATUS GuIoClose(VOID){return EFI_SUCCESS;}
EFI_STATUS GuLoadAssets(VOID){return EFI_SUCCESS;}
VOID GuReleaseAssets(VOID){}
BOOLEAN GuTargetConfig(const UINT32 *c,UINTN s,UINTN b,UINTN d,UINTN f){return c && c[0]==0x268410deU && !s && b==2 && !d && !f;}
EFI_STATUS GuSaveBlob(CHAR16 *name,const VOID *data,UINTN size){
  assert(name && data && size);
  if(NameIs(name,L"CONFIG.BIN") || NameIs(name,L"ROM.BIN") || NameIs(name,L"PROM.BIN"))saved++;
  else extra_saved++;
  return scenario==7?EFI_DEVICE_ERROR:EFI_SUCCESS;
}
EFI_STATUS GuSavePromDump(const VOID *data,UINTN size){assert(size==1048576);return GuSaveBlob(L"PROM.BIN",data,size);}
VOID GuCopyFromIo(VOID *d,const VOID *s,size_t n){
  assert((UINTN)s==0x80300000 && n==1048576);memset(d,0,n);((UINT8 *)d)[0]=0x55;((UINT8 *)d)[1]=0xaa;
  if(scenario==8)Gu.fault=TRUE;
}
UINT32 GuRead32(UINT32 offset){
  switch(offset){case 0:return scenario==4?0x193000a1:0x192000a1;
    case 0x1183a4:return 24576;case 0x1fa828:return scenario==5?0x100:0;
    case 0x82381c:return scenario==9?1161179158U:0x44023025;
    case 0x823820:return scenario==9?3:scenario==10?8:7;default:abort();}
}
static EFI_STATUS EFIAPI Locate(EFI_LOCATE_SEARCH_TYPE type,EFI_GUID *g,VOID *key,UINTN *n,EFI_HANDLE **out){
  (void)type;(void)key;if(memcmp(g,&test_pci_guid,sizeof(*g)))return EFI_NOT_FOUND;
  *n=scenario==2?2:1;*out=calloc(*n,sizeof(**out));
  (*out)[0]=(EFI_HANDLE)1;if(*n==2)(*out)[1]=(EFI_HANDLE)2;return EFI_SUCCESS;
}
static EFI_STATUS EFIAPI Handle(EFI_HANDLE h,EFI_GUID *g,VOID **out){(void)h;(void)g;*out=&pci;return EFI_SUCCESS;}
static EFI_STATUS EFIAPI Read(EFI_PCI_IO_PROTOCOL *p,EFI_PCI_IO_PROTOCOL_WIDTH w,UINT32 off,UINTN n,VOID *out){
  (void)p;assert(w==EfiPciIoWidthUint32 && n==1 && off<256);*(UINT32 *)out=config[off/4];return EFI_SUCCESS;
}
static EFI_STATUS EFIAPI Write(EFI_PCI_IO_PROTOCOL *p,EFI_PCI_IO_PROTOCOL_WIDTH w,UINT32 off,UINTN n,VOID *in){
  (void)p;(void)w;(void)off;(void)n;(void)in;writes++;return EFI_DEVICE_ERROR;
}
static EFI_STATUS EFIAPI Location(EFI_PCI_IO_PROTOCOL *p,UINTN *s,UINTN *b,UINTN *d,UINTN *f){
  (void)p;*s=0;*b=2;*d=*f=0;return EFI_SUCCESS;
}
static EFI_STATUS EFIAPI Bar(EFI_PCI_IO_PROTOCOL *p,UINT8 index,UINT64 *supports,VOID **out){
  (void)p;(void)supports;assert(index==0);
  EFI_ACPI_ADDRESS_SPACE_DESCRIPTOR *r=calloc(1,sizeof(*r)+2);
  r->Desc=ACPI_ADDRESS_SPACE_DESCRIPTOR;r->Len=sizeof(*r)-3;r->AddrRangeMin=0x80000000;
  r->AddrLen=scenario==6?4096:0x1000000;r->AddrSpaceGranularity=32;*out=r;return EFI_SUCCESS;
}
static EFI_STATUS EFIAPI Stall(UINTN n){assert(n==5000000);return EFI_SUCCESS;}
static EFI_STATUS EFIAPI Variable(CHAR16 *name,EFI_GUID *guid,UINT32 *attributes,UINTN *size,VOID *data){
  (void)name;(void)guid;(void)attributes;
  if(!NameIs(name,L"SecureBoot"))return EFI_NOT_FOUND;
  if(!data){*size=1;return EFI_BUFFER_TOO_SMALL;}
  assert(*size==1);*(UINT8 *)data=scenario==11?1:scenario==12?2:0;
  if(scenario==13)return EFI_NOT_FOUND;
  if(scenario==14)*size=2;
  return EFI_SUCCESS;
}
static EFI_STATUS EFIAPI MemRead(EFI_PCI_IO_PROTOCOL *p,EFI_PCI_IO_PROTOCOL_WIDTH width,UINT8 bar,UINT64 off,UINTN count,VOID *data){
  (void)p;assert(width==EfiPciIoWidthUint32 && !bar);
  if(off>=0x300000 && off<0x400000){
    assert(count==256 && off+count*4<=0x400000);
    if(scenario==17)return EFI_DEVICE_ERROR;
    memset(data,0,count*4);if(off==0x300000){((UINT8 *)data)[0]=0x55;((UINT8 *)data)[1]=0xaa;}
  } else {
    assert(count==1 && off<0xa00000);
    if(scenario==16 && off==0x823818)return EFI_DEVICE_ERROR;
    *(UINT32 *)data=off==0x118128?1:off==0x118234?0xff:off==0x110100?0x10:0x12345678;
  }
  return EFI_SUCCESS;
}
int main(void){
  bs.LocateHandleBuffer=Locate;bs.HandleProtocol=Handle;bs.Stall=Stall;
  pci.Pci.Read=Read;pci.Pci.Write=Write;pci.GetLocation=Location;pci.GetBarAttributes=Bar;
  pci.Mem.Read=MemRead;
  rom[0]=0x55;rom[1]=0xaa;pci.RomImage=rom;pci.RomSize=sizeof(rom);
  rt.GetVariable=Variable;
  EFI_SYSTEM_TABLE table={0};table.BootServices=&bs;table.RuntimeServices=&rt;
  for(scenario=0;scenario<18;scenario++){
    pci.RomImage=scenario==15?NULL:rom;
    saved=complete=writes=extra_saved=0;memset(config,0,sizeof(config));config[0]=scenario==1?0x270410de:0x268410de;
    config[1]=scenario==3?6:0x00100002;config[2]=0x030000a1;
    config[0x34/4]=0x60;config[0x60/4]=0x00017001;config[0x70/4]=0x00020010;config[0x74/4]=1U<<28;
    EFI_STATUS status=EfiMain((EFI_HANDLE)3,&table);
    if(!scenario || scenario==9 || scenario==11 || scenario==16 || scenario==17){
      assert(!EFI_ERROR(status) && saved==3 && complete==1 && extra_saved>=4);
    }
    else assert(EFI_ERROR(status) && !complete);
    if(scenario==15)assert(saved==2); /* Preserve CONFIG and PROM if PCI ROM is absent. */
    assert(!writes && !Gu.mmio_writes && !Gu.dma_count && !Gu.started && !Gu.armed);
  }
  puts("18 probe scenarios passed, including firmware research capture and optional read failures; no GPU writes.");
  return 0;
}
