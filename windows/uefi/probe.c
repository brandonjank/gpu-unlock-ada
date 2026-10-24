// SPDX-License-Identifier: GPL-2.0-only
/* Read GPU state before Windows starts. No PCI writes, DMA, driver release,
 * firmware execution, reset, or boot-variable changes are reachable here. */
#include "app_io.h"
#include "compat/compat.h"
#include "sha256.h"
#include "state_checks.h"
#include "security.h"
#include "research.h"
#include "boot_tests.h"
#include <IndustryStandard/Acpi.h>

static EFI_GUID PciGuid=EFI_PCI_IO_PROTOCOL_GUID;
static EFI_SYSTEM_TABLE *GuProbeSystemTable;

static VOID Hash(const char *Name,const VOID *Data,UINTN Bytes) {
  UINT8 digest[32];char hex[65];static const char digits[]="0123456789abcdef";
  GuSha256(Data,Bytes,digest);
  for(UINTN i=0;i<32;i++){hex[2*i]=digits[digest[i]>>4];hex[2*i+1]=digits[digest[i]&15];}
  hex[64]=0;GuLog("PROFILE %s_sha256=%s\n",Name,hex);
  const char *file=!strcmp(Name,"config")?"CONFIG.BIN":!strcmp(Name,"rom")?"ROM.BIN":"PROM.BIN";
  GuLog("CAPTURE file=%s bytes=%zu sha256=%s verified=1\n",file,(size_t)Bytes,hex);
}

static EFI_STATUS Capture(VOID) {
  UINT32 config[64];UINTN s,b,d,f;
  EFI_STATUS status=Gu.pci->GetLocation(Gu.pci,&s,&b,&d,&f);
  if(EFI_ERROR(status))return status;
  for(UINTN i=0;i<64;i++)
    if(EFI_ERROR(Gu.pci->Pci.Read(Gu.pci,EfiPciIoWidthUint32,i*4,1,&config[i])))return EFI_DEVICE_ERROR;
  if(config[0]!=0x268410deU || (config[2]>>24)!=3 || (config[1]&6)!=2 ||
     (config[3]&0x7f0000U) || (config[12]&1))return EFI_UNSUPPORTED;
  EFI_ACPI_ADDRESS_SPACE_DESCRIPTOR *bar=NULL;
  status=Gu.pci->GetBarAttributes(Gu.pci,0,NULL,(VOID **)&bar);
  if(EFI_ERROR(status))return status;
  if(!bar || bar->Desc!=ACPI_ADDRESS_SPACE_DESCRIPTOR || bar->Len!=sizeof(*bar)-3 ||
     bar->ResType || bar->AddrTranslationOffset || bar->AddrLen!=0x1000000 ||
     !bar->AddrRangeMin || bar->AddrRangeMin>~0ULL-bar->AddrLen ||
     (bar->AddrSpaceGranularity!=32 && bar->AddrSpaceGranularity!=64)) {
    GuFree(bar);return EFI_UNSUPPORTED;
  }
  Gu.bar_base=bar->AddrRangeMin;Gu.bar_size=bar->AddrLen;
  GuSaveCapture(L"BAR0.BIN","BAR0.BIN",bar,sizeof(*bar));
  GuLog("PROFILE segment=%zu\nPROFILE bus=%zu\nPROFILE device=%zu\nPROFILE function=%zu\n",
    (size_t)s,(size_t)b,(size_t)d,(size_t)f);
  GuLog("PROFILE bar_base=%llu\nPROFILE bar_size=%llu\nPROFILE bar_granularity=%llu\n",
    (unsigned long long)Gu.bar_base,(unsigned long long)Gu.bar_size,
    (unsigned long long)bar->AddrSpaceGranularity);
  GuFree(bar);
  UINT32 chip=GuRead32(0),vram=GuRead32(0x1183a4),wpr2=GuRead32(0x1fa828);
  UINT32 ss0=GuRead32(0x82381c),ss1=GuRead32(0x823820);
  GuLog("PROFILE chip=%u\nPROFILE vram_mib=%u\nPROFILE wpr2_hi=%u\nPROFILE ss0=%u\nPROFILE ss1=%u\n",
    chip,vram,wpr2,ss0,ss1);
  if(Gu.fault || chip!=0x192000a1U)return EFI_NOT_READY;
  BOOLEAN eligible=!(wpr2>>4) && GuColdSelectors(ss0,ss1) && vram>=24512 && vram<=24576;
  GuLog("PROFILE eligible_for_unlock=%u\n",eligible);
  GuLogText("Backup capture can continue when unlock eligibility fails; no unlock is attempted.\n");
  status=GuSaveBlob(L"CONFIG.BIN",config,sizeof(config));if(EFI_ERROR(status))return status;
  Hash("config",config,sizeof(config));
  GuBootTestPci(config);
  GuBootTestReadiness();
  GuBootTestEnvironment(GuProbeSystemTable);
  UINT64 attributes=0;
  EFI_STATUS attr_status=Gu.pci->Attributes?Gu.pci->Attributes(Gu.pci,EfiPciIoAttributeOperationGet,0,&attributes):EFI_UNSUPPORTED;
  GuLog("PCI attributes=%#llx status=%#llx ROM_from_platform=%u\n",
    (unsigned long long)attributes,(unsigned long long)attr_status,!!(attributes&EFI_PCI_IO_ATTRIBUTE_EMBEDDED_ROM));
  GuResearchRegisters(L"REGS0.BIN","REGS0.BIN");
  EFI_STATUS rom_status=EFI_UNSUPPORTED;
  GuLog("PROFILE rom_bytes=%zu\n",(size_t)Gu.pci->RomSize);
  if(Gu.pci->RomImage && Gu.pci->RomSize && Gu.pci->RomSize<=16U*1048576) {
    rom_status=GuSaveBlob(L"ROM.BIN",Gu.pci->RomImage,(UINTN)Gu.pci->RomSize);
    if(!EFI_ERROR(rom_status)) {
      Hash("rom",Gu.pci->RomImage,(UINTN)Gu.pci->RomSize);
      GuBootTestFirmware(Gu.pci->RomImage,(UINTN)Gu.pci->RomSize,FALSE);
    }
  }
  GuLog("PCI ROM capture status=%#llx; continue collecting PROM\n",(unsigned long long)rom_status);
  VOID *prom=GuAlloc(1048576);if(!prom)return EFI_OUT_OF_RESOURCES;
  GuCopyFromIo(prom,(VOID *)(UINTN)(Gu.bar_base+0x300000),1048576);
  status=Gu.fault?EFI_DEVICE_ERROR:GuSavePromDump(prom,1048576);
  if(!EFI_ERROR(status)) {
    UINT8 digest[32];Hash("prom",prom,1048576);GuSha256(prom,1048576,digest);
    GuBootTestFirmware(prom,1048576,TRUE);
    GuResearchPromRepeat(prom,digest);
  }
  GuResearchRegisters(L"REGS1.BIN","REGS1.BIN");
  GuBootTestReadiness();
  GuBootTestAssets();
  GuFree(prom);
  return EFI_ERROR(status)?status:EFI_ERROR(rom_status)?rom_status:eligible?EFI_SUCCESS:EFI_NOT_READY;
}

EFI_STATUS EFIAPI EfiMain(EFI_HANDLE Image,EFI_SYSTEM_TABLE *St) {
  if(!St || !St->BootServices)return EFI_INVALID_PARAMETER;
  GuProbeSystemTable=St;
  GuInit(St->BootServices,NULL);Gu.image=Image;GuScreenDetached=FALSE;
  EFI_STATUS status=GuIoOpen(Image,St);
  if(EFI_ERROR(status))return status;
  GuLogText("PROBE ONLY: GPU reads and new files on this USB; no unlock attempt.\n");
  GuLogText("PROBE version=4; backup plus read-only boot test suite; no GPU/boot-setting changes.\n");
  UINT8 secure=0xff;
  status=GuReadSecureBoot(St->RuntimeServices,&secure);
  GuLog("SECURITY SecureBoot=%u status=%#llx firmware_policy_unchanged=1\n",
    (unsigned)secure,(unsigned long long)status);
  if(EFI_ERROR(status))goto finish;
  GuResearchPlatform(St);
  EFI_HANDLE *handles=NULL;UINTN count=0,matches=0;
  status=Gu.bs->LocateHandleBuffer(ByProtocol,&PciGuid,NULL,&count,&handles);
  if(!EFI_ERROR(status) && (!handles || count>256))status=EFI_COMPROMISED_DATA;
  for(UINTN i=0;!EFI_ERROR(status) && i<count;i++) {
    EFI_PCI_IO_PROTOCOL *pci=NULL;UINT32 id=0;
    status=Gu.bs->HandleProtocol(handles[i],&PciGuid,(VOID **)&pci);
    if(!EFI_ERROR(status) && pci)status=pci->Pci.Read(pci,EfiPciIoWidthUint32,0,1,&id);
    else if(!EFI_ERROR(status))status=EFI_COMPROMISED_DATA;
    if(!EFI_ERROR(status) && id==0x268410deU){matches++;Gu.pci=pci;Gu.handle=handles[i];}
  }
  GuFree(handles);
  if(!EFI_ERROR(status))status=matches==1?Capture():EFI_UNSUPPORTED;
finish:
  if(!EFI_ERROR(status) && GuLogReady())GuLogText("PROFILE complete=1\n");
  GuLog("PROBE FINAL status=%#llx GPU writes=%u DMA maps=%u\n",
    (unsigned long long)status,Gu.mmio_writes,Gu.dma_count);
  if(!GuLogReady())status=EFI_DEVICE_ERROR;
  EFI_STATUS closed=GuIoClose();if(EFI_ERROR(closed))status=closed;
  GuConsole("Probe finished. Power off; return to Windows using your normal boot entry.\n");
  /* Give the firmware console time to display the result, without any reset. */
  Gu.bs->Stall(5000000);
  return status;
}
