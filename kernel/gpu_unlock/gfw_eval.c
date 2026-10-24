// SPDX-License-Identifier: GPL-2.0-only
#ifdef __KERNEL__
#include <linux/errno.h>
#else
#include <errno.h>
#endif

#include "gfw_eval.h"

/* PRI error values can have every completion bit set (upstream issue #42). */
static bool gfw_inaccessible(u32 value)
{
	return value == (u32)~0U || (value & 0xffff0000u) == 0xbadf0000u;
}

int gpu_unlock_gfw_assess(const struct gpu_unlock_gfw_sample *sample)
{
	if (!sample || !sample->config_ok)
		return -ENODEV;
	if (gfw_inaccessible(sample->plm) || gfw_inaccessible(sample->boot) ||
	    gfw_inaccessible(sample->cpuctl))
		return -ENODEV;
	if (!(sample->cpuctl & GU_GFW_CPUCTL_HALTED))
		return -EAGAIN;
	if (!(sample->plm & GU_GFW_PLM_LEVEL0))
		return -EAGAIN;
	if ((sample->boot & 0xffu) != GU_GFW_BOOT_COMPLETED)
		return -EAGAIN;
	return 0;
}

u16 gpu_unlock_command_restore(u16 original, u16 live)
{
	u16 mask = GU_PCI_COMMAND_MEMORY | GU_PCI_COMMAND_MASTER;

	return (live & (u16)~mask) | (original & mask);
}
