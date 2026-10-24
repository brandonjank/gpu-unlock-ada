// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#ifndef GU_PROBE_ONLY
#error An unlock build requires a board_profile.h generated from a successful USB probe.
#endif
/* Used only to compile unused compatibility helpers in the read-only probe. */
#define GU_BOARD_ID 0x268410deU
#define GU_BOARD_SUBSYSTEM 0U
#define GU_BOARD_CHIP 0x192000a1U
#define GU_SEGMENT 0U
#define GU_BUS 0U
#define GU_DEVICE 0U
#define GU_FUNCTION 0U
