#include <gum/guminterceptor.h>
#include <stdint.h>

extern void acquire(void *lock);
extern void release(void *lock);
typedef struct {
  void *lock;
  uint64_t counts[10];
} State;
extern State state;
/* Counter order is documented in recorder.py. No writes to game memory. */
void count_heavy(int weapon, int64_t threshold, int64_t random_scaled) {
  acquire(&state.lock);
  if (weapon == 0) {
    state.counts[0]++;
    /* Exactly the signed CMP/JLE in the game: equality is a miss. */
    if (threshold > random_scaled) state.counts[1]++;
    else state.counts[2]++;
  } else if (weapon == 2) state.counts[7]++;
  else if (weapon == 1) state.counts[8]++;
  else state.counts[9]++;
  release(&state.lock);
}
void count_air(int64_t planes, int successes) {
  acquire(&state.lock);
  if (planes > 0 && successes >= 0 && (int64_t)successes <= planes) {
    state.counts[3]++;
    state.counts[4]+=(uint64_t)planes;
    state.counts[5]+=(uint64_t)successes;
    if(successes == 0) state.counts[6]++;
  } else state.counts[9]++;
  release(&state.lock);
}
void heavy_probe(GumInvocationContext *ctx) {
  GumCpuContext *cpu = ctx->cpu_context;
  count_heavy(*(int *)((uintptr_t)cpu->rbp + 0xa0),
              *(int64_t *)((uintptr_t)cpu->rbp - 0x38), (int64_t)cpu->rcx);
}
void air_probe(GumInvocationContext *ctx) {
  GumCpuContext *cpu = ctx->cpu_context;
  count_air((int64_t)cpu->rsi,(int32_t)(uint32_t)cpu->rax);
}
void snapshot(uint64_t *out) {
  int i;
  acquire(&state.lock);
  for(i=0;i<10;i++) out[i]=state.counts[i];
  release(&state.lock);
}
