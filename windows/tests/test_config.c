// SPDX-License-Identifier: GPL-2.0-only
#include "checks.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

VOID GuLog(const char *format,...){(void)format;}
int main(void){
  UINT32 c[64]={0},original[64];GU_CAPS caps;
  c[0]=GU_BOARD_ID;c[1]=0x00100002;c[2]=0x030000a1;c[11]=GU_BOARD_SUBSYSTEM;
  c[0x34/4]=0x60;c[0x60/4]=0x00017001;c[0x70/4]=0x00020010;c[0x74/4]=1U<<28;
  memcpy(original,c,sizeof(c));
  assert(GuTargetConfig(c,0,2,0,0));
  assert(GuCheckConfig(c,0,2,0,0,&caps) && caps.pm==0x60 && caps.pcie==0x70);
  assert(!GuTargetConfig(c,0,1,0,0) && !GuCheckConfig(c,0,1,0,0,&caps));
  for(int scenario=0;scenario<7;scenario++){
    memcpy(c,original,sizeof(c));
    switch(scenario){
      case 0:c[0]=0x270410de;break;
      case 1:c[11]^=1;break;
      case 2:c[1]|=4;break;
      case 3:c[0x64/4]=3;break;
      case 4:c[0x60/4]=0x00016001;break;
      case 5:c[0x74/4]=0;break;
      case 6:c[0x78/4]=0x8000;break;
    }
    assert(!GuCheckConfig(c,0,2,0,0,&caps));
  }
  puts("9 profile-pinned PCI guard scenarios passed.");
  return 0;
}
