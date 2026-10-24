// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#include "port.h"
VOID GuBootTestPci(const UINT32 Config[64]);
VOID GuBootTestFirmware(const VOID *Data,UINTN Bytes,BOOLEAN Prom);
VOID GuBootTestReadiness(VOID);
VOID GuBootTestAssets(VOID);
VOID GuBootTestEnvironment(EFI_SYSTEM_TABLE *Table);
