// SPDX-License-Identifier: GPL-2.0-only
#include "../uefi/app_io.c"
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>

GU_PLATFORM Gu;
GU_ASSET GuAssets[5];
VOID *GuAlloc(size_t size){return calloc(1,size);}
VOID GuFree(VOID *p){free(p);}
BOOLEAN GuSafeToReturn(VOID){return TRUE;}
static EFI_FILE_PROTOCOL directory,file;
static UINT8 *storage;
static UINTN length,position;
static int mode,write_calls,read_calls;
static EFI_STATUS EFIAPI Close(EFI_FILE_PROTOCOL *f){(void)f;return EFI_SUCCESS;}
static EFI_STATUS EFIAPI Open(EFI_FILE_PROTOCOL *d,EFI_FILE_PROTOCOL **out,CHAR16 *name,UINT64 flags,UINT64 attr){
  (void)d;(void)name;(void)attr;
  if(!(flags&EFI_FILE_MODE_CREATE) && mode!=5)return EFI_NOT_FOUND;
  *out=&file;return EFI_SUCCESS;
}
static EFI_STATUS EFIAPI Write(EFI_FILE_PROTOCOL *f,UINTN *n,VOID *data){
  (void)f;write_calls++;assert(*n<=1048576);
  if(mode==1){(*n)--;return EFI_SUCCESS;}
  memcpy(storage+position,data,*n);position+=*n;length=position;return EFI_SUCCESS;
}
static EFI_STATUS EFIAPI Read(EFI_FILE_PROTOCOL *f,UINTN *n,VOID *data){
  (void)f;read_calls++;assert(*n<=4096 && position+*n<=length);
  if(mode==6){(*n)--;return EFI_SUCCESS;}
  memcpy(data,storage+position,*n);if(mode==3)((UINT8 *)data)[0]^=1;
  position+=*n;return EFI_SUCCESS;
}
static EFI_STATUS EFIAPI Flush(EFI_FILE_PROTOCOL *f){(void)f;return mode==2?EFI_DEVICE_ERROR:EFI_SUCCESS;}
static EFI_STATUS EFIAPI Position(EFI_FILE_PROTOCOL *f,UINT64 p){(void)f;assert(!p);position=0;return mode==7?EFI_DEVICE_ERROR:EFI_SUCCESS;}
static EFI_STATUS EFIAPI Info(EFI_FILE_PROTOCOL *f,EFI_GUID *guid,UINTN *n,VOID *data){
  (void)f;(void)guid;assert(*n>=SIZE_OF_EFI_FILE_INFO+2);
  EFI_FILE_INFO *i=data;memset(data,0,*n);i->Size=SIZE_OF_EFI_FILE_INFO+2;
  i->FileSize=mode==4?length+1:length;*n=(UINTN)i->Size;return EFI_SUCCESS;
}
int main(void){
  UINTN size=1048576+17;UINT8 *input=malloc(size);storage=malloc(size);
  assert(input && storage);for(UINTN i=0;i<size;i++)input[i]=(UINT8)i;
  directory.Open=Open;Run=&directory;
  file.Write=Write;file.Read=Read;file.Flush=Flush;file.SetPosition=Position;file.GetInfo=Info;file.Close=Close;
  for(mode=0;mode<8;mode++){
    length=position=0;write_calls=read_calls=0;
    EFI_STATUS status=GuSaveBlob(L"ROM.BIN",input,size);
    if(!mode){assert(!EFI_ERROR(status) && write_calls==2 && read_calls>256 && !memcmp(input,storage,size));}
    else assert(EFI_ERROR(status));
    if(mode==5)assert(!write_calls && !read_calls);
  }
  free(input);free(storage);
  puts("8 USB backup verification scenarios passed: chunked writes, exact size, readback, corruption and duplicate-file checks.");
  return 0;
}
