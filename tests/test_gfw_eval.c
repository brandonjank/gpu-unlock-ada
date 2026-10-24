// SPDX-License-Identifier: GPL-2.0-only
#include <assert.h>
#include <errno.h>
#include <stdio.h>

#include "gfw_eval.h"

int main(void)
{
	struct gpu_unlock_gfw_sample sample = {
		.config_ok = true,
		.plm = GU_GFW_PLM_LEVEL0,
		.boot = GU_GFW_BOOT_COMPLETED,
		.cpuctl = GU_GFW_CPUCTL_HALTED,
	};

	assert(gpu_unlock_gfw_assess(&sample) == 0);
	/* Every PRI-error field can independently look complete; mixed samples
	 * must be rejected before interpreting any completion bits. */
	for (unsigned int mask = 1; mask < 8; mask++) {
		struct gpu_unlock_gfw_sample bad = sample;
		if (mask & 1) bad.plm = 0xbadf0001;
		if (mask & 2) bad.boot = 0xbadf00ff;
		if (mask & 4) bad.cpuctl = 0xbadf0010;
		assert(gpu_unlock_gfw_assess(&bad) == -ENODEV);
	}
	for (unsigned int field = 0; field < 3; field++) {
		struct gpu_unlock_gfw_sample bad = sample;
		if (field == 0) bad.plm = ~0u;
		if (field == 1) bad.boot = ~0u;
		if (field == 2) bad.cpuctl = ~0u;
		assert(gpu_unlock_gfw_assess(&bad) == -ENODEV);
	}
	assert(gpu_unlock_gfw_assess(NULL) == -ENODEV);
	sample.cpuctl = 0;
	assert(gpu_unlock_gfw_assess(&sample) == -EAGAIN);
	sample.cpuctl = GU_GFW_CPUCTL_HALTED;
	sample.plm = 0;
	assert(gpu_unlock_gfw_assess(&sample) == -EAGAIN);
	sample.plm = GU_GFW_PLM_LEVEL0;
	sample.boot = 0xfe;
	assert(gpu_unlock_gfw_assess(&sample) == -EAGAIN);
	sample.boot = (u32)~0U;
	sample.plm = (u32)~0U;
	sample.cpuctl = (u32)~0U;
	assert(gpu_unlock_gfw_assess(&sample) == -ENODEV);
	sample.boot = GU_GFW_BOOT_COMPLETED;
	sample.plm = GU_GFW_PLM_LEVEL0;
	sample.cpuctl = GU_GFW_CPUCTL_HALTED;
	sample.config_ok = false;
	assert(gpu_unlock_gfw_assess(&sample) == -ENODEV);

	assert(gpu_unlock_command_restore(0, GU_PCI_COMMAND_MEMORY |
					  GU_PCI_COMMAND_MASTER) == 0);
	assert(gpu_unlock_command_restore(GU_PCI_COMMAND_MEMORY,
					  GU_PCI_COMMAND_MEMORY |
					  GU_PCI_COMMAND_MASTER) ==
	       GU_PCI_COMMAND_MEMORY);
	assert(gpu_unlock_command_restore(GU_PCI_COMMAND_IO,
					  GU_PCI_COMMAND_IO | GU_PCI_COMMAND_MEMORY) ==
	       GU_PCI_COMMAND_IO);

	puts("gfw predicate and command restore checks passed");
	return 0;
}
