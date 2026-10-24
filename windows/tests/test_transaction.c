// SPDX-License-Identifier: GPL-2.0-only
/* Actual retained UEFI sampler/launch code against CPU-only PCI/MMIO mocks.
 * Unused transaction paths are discarded by the host linker, never executed. */
/* Keep the three public entry points private to this unit-test translation
 * unit, so COFF and ELF both discard their unrelated hardware dependencies. */
#define gpu_unlock_610_load_shared static __attribute__((unused)) test_load_shared
#define gpu_unlock_610_release_shared static __attribute__((unused)) test_release_shared
#define gpu_unlock_610_unlock static __attribute__((unused)) test_unlock
#include "../uefi/vendor/unlock_610.c"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>
#include <stdio.h>
#include <string.h>

GU_PLATFORM Gu;
static u32 regs[0x1000000/4], identity;
static unsigned int writes, started, boot_reads, early_reads;
static bool recover;
static ktime_t ticks;
VOID GuLog(const char *format, ...){(void)format;}
VOID GuStarted(VOID){Gu.started=TRUE;Gu.quiesced=FALSE;started++;}
ktime_t ktime_get(void){return ticks;}
void usleep_range(unsigned long a,unsigned long b){(void)b;ticks+=a;}
void dma_wmb(void){}
u32 readl(const void *p){
    size_t n=((const u8 *)p-(const u8 *)regs)/4;
    assert(n<ARRAY_SIZE(regs));
    if(n==GU_GFW_CPUCTL_OFFSET/4 && recover && ++early_reads<3)return 0xbadf0010;
    if(n==GU_GFW_BOOT_OFFSET/4){
        assert(!inaccessible(regs[GU_GFW_PLM_OFFSET/4]) && (regs[GU_GFW_PLM_OFFSET/4]&1));
        boot_reads++;
    }
    return regs[n];
}
void writel(u32 v,void *p){size_t n=((u8 *)p-(u8 *)regs)/4;assert(n<ARRAY_SIZE(regs));regs[n]=v;writes++;}
int pci_read_config_dword(struct pci_dev *p,int r,u32 *v){(void)p;assert(r==PCI_VENDOR_ID);*v=identity;return 0;}
int pcie_capability_read_dword(struct pci_dev *p,int r,u32 *v){(void)p;(void)r;*v=0;return 0;}

static void setup(struct unlock_transaction_work *w,struct pci_dev *p){
    memset(w,0,sizeof(*w));memset(regs,0,sizeof(regs));memset(&Gu,0,sizeof(Gu));
    writes=started=boot_reads=early_reads=0;ticks=0;recover=false;identity=GU_TARGET_PCI_ID;
    w->pdev=p;w->mapped=true;w->bar=regs;w->bar_len=sizeof(regs);
    regs[GU_GFW_PLM_OFFSET/4]=1;regs[GU_GFW_BOOT_OFFSET/4]=0xff;
    regs[GU_GFW_CPUCTL_OFFSET/4]=0x10;regs[GU_FEAT_PLM_OFFSET/4]=0x8f;
}
int main(void){
    struct pci_dev p={0};struct unlock_transaction_work w;
    for(int mode=0;mode<7;mode++){
        setup(&w,&p);
        if(mode==0)regs[GU_GFW_PLM_OFFSET/4]=0xbadf0001;
        if(mode==1)regs[GU_GFW_BOOT_OFFSET/4]=0xbadf00ff;
        if(mode==2)regs[GU_GFW_CPUCTL_OFFSET/4]=0xbadf0010;
        if(mode==3)regs[GU_GFW_PLM_OFFSET/4]=0;
        if(mode==4)identity^=0x10000;
        if(mode==5)recover=true;
        int ret=unlock_transaction_gfw(&w);
        assert(ret==(mode==4?-ENODEV:mode>=5?0:-ETIMEDOUT));
        assert(!writes && !started && !w.firmware_started && !Gu.started);
        if(mode==0 || mode==3 || mode==4)assert(!boot_reads);
        if(mode==5)assert(early_reads==3);
    }
    const struct falcon_eng eng={0x110000,0x110600,0x111000};
    /* Exercise falcon_hs itself, including rejected DMEM after valid IMEM.
     * No reset, DMA, or global started marker is allowed on rejection. */
    for(int mode=0;mode<4;mode++){
        setup(&w,&p);
        dma_addr_t image=mode==0?0x100001:0x100000;
        u32 data_pa=mode==1?0x1000000:0, code_va=mode==2?0x200000:0;
        if(mode==3)image=~0ull-127;
        int ret=falcon_hs(&w,&eng,0,256,code_va,0,256,256,data_pa,0,1,3,image,0,0,false,false);
        assert(ret<0 && !writes && !started && !w.firmware_started && !Gu.started);
    }
    setup(&w,&p);regs[(eng.base+0x118)/4]=0;
    assert(falcon_dma(&w,eng.base,0,0,0x100000,256,0x614)==-ETIMEDOUT);
    assert(started==1 && w.firmware_started && Gu.started && writes>0);
    puts("UEFI initial GFW guards and DMA lifetime boundary passed (12 scenarios).");
    return 0;
}
