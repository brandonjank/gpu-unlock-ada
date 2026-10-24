// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#include <Uefi.h>

/* SS0 has eight 4-bit selectors; SS1 has one. Bit 3 enables each
 * override. Lower bits vary between boards/boots (this 4090 reports SS1=3).
 * A disabled override need not have the previous board's value of 7. */
static inline BOOLEAN GuColdSelectors(UINT32 Ss0,UINT32 Ss1) {
  return !(Ss0&0x88888888U) && !(Ss1&~7U);
}
