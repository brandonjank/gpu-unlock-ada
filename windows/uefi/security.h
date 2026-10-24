// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#include <Uefi.h>
#include <Guid/GlobalVariable.h>

/* Firmware decides whether this image may execute. An explicitly enrolled
 * image can run with Secure Boot on; never modify firmware trust variables. */
static inline EFI_STATUS GuReadSecureBoot(EFI_RUNTIME_SERVICES *Runtime,UINT8 *Secure) {
  EFI_GUID global=EFI_GLOBAL_VARIABLE;
  UINTN bytes=1;
  if(!Runtime || !Runtime->GetVariable || !Secure)return EFI_INVALID_PARAMETER;
  *Secure=0xff;
  EFI_STATUS status=Runtime->GetVariable(L"SecureBoot",&global,NULL,&bytes,Secure);
  if(EFI_ERROR(status))return status;
  return bytes==1 && *Secure<=1?EFI_SUCCESS:EFI_SECURITY_VIOLATION;
}
