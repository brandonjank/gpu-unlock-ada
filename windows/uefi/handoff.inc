/* Modified 2026-10-21: experimental AD103 32GB GA102-pair port; see PORT-NOTES.txt. */
/* Derived from the v0.3 handoff path exercised on this user's single AD103. */
#include "boot_manager.inc"
static EFI_STATUS VerifySelectors(const char *phase) {
  UINT32 ss0=GuRead32(0x82381c),ss1=GuRead32(0x823820);
  UINT32 readout=GuRead32(0x823818);
  GuLog("%s SS0=0x%08x SS1=0x%08x\n",phase,ss0,ss1);
  GuLog("%s unlock_matched=%u; handoff checks GPU accessibility separately\n",phase,ss0==0x88888888 && ss1==8);
  GuLog("%s register_unlock_verified=%u readout1=%#x windows_driver_verified=0\n",
    phase,ss0==0x88888888 && ss1==8 && !(readout&0x07ffffffU),readout);
  return !Gu.fault && GuLogReady() && ss0!=0xffffffff && ss1!=0xffffffff &&
    ss0!=0xbadf5620 && ss1!=0xbadf5620 && readout!=0xffffffff &&
    (readout&0xffff0000U)!=0xbadf0000U?EFI_SUCCESS:EFI_DEVICE_ERROR;
}
static EFI_STATUS RestoreDisplayForWindows(EFI_HANDLE Driver) {
  if(!WindowsImage || !Driver || !GuScreenDetached || !GuSafeToReturn() || !Gu.quiesced ||
     Gu.flrs!=1 || Gu.allocations || Gu.dma_count || !Gu.owned || Gu.fault)return EFI_NOT_READY;
  EFI_STATUS s=VerifySelectors("POST-FLR");if(EFI_ERROR(s))return s;
  GuLogText("stage=before_GOP_reconnect; transaction quiesced, DMA released, PCI restored\n");
  if(!GuLogReady())return EFI_DEVICE_ERROR;
  s=Gu.bs->CloseProtocol(Gu.handle,&PciGuid,Gu.image,NULL);if(EFI_ERROR(s))return s;
  Gu.owned=FALSE;
  EFI_HANDLE drivers[2]={Driver,NULL};
  s=Gu.bs->ConnectController(Gu.handle,drivers,NULL,TRUE);
  GuLog("ConnectController status=%#llx\n",(unsigned long long)s);
  if(EFI_ERROR(s))return s;
  s=GuRefreshTargetPci();if(EFI_ERROR(s))return s;
  ExpectDetached=FALSE;
  if(!DisplayCheck())return EFI_DEVICE_ERROR;
  UINT16 command=0;UINT32 value=0;
  s=GuConfigRead(EfiPciIoWidthUint16,4,&command);
  if(EFI_ERROR(s)||command!=(UINT16)InitialConfig[1]||(command&4))return EFI_DEVICE_ERROR;
  for(UINT32 offset=0x10;offset<=0x24;offset+=4) {
    s=GuConfigRead(EfiPciIoWidthUint32,offset,&value);
    if(EFI_ERROR(s)||value!=InitialConfig[offset/4])return EFI_DEVICE_ERROR;
  }
  s=VerifySelectors("POST-GOP");if(EFI_ERROR(s))return s;
  GuLogText("stage=before_StartImage; POST-GOP selectors and PCI BAR/command verified\n");
  if(!GuLogReady())return EFI_DEVICE_ERROR;
  GuScreenDetached=FALSE;
  return EFI_SUCCESS;
}
