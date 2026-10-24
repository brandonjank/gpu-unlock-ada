// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#include "port.h"
VOID GuResearchPlatform(EFI_SYSTEM_TABLE *Table);
EFI_STATUS GuResearchRegisters(CHAR16 *File,const char *Name);
EFI_STATUS GuSaveCapture(CHAR16 *File,const char *Name,const VOID *Data,UINTN Bytes);
VOID GuResearchPromRepeat(VOID *Buffer,const UINT8 FirstHash[32]);
