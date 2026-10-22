/* Fixed input/replay interface. Only guard.inc is replaceable by the LLM. */
#include <klee/klee.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <float.h>

_Static_assert(sizeof(double) == sizeof(uint64_t), "binary64 required");
_Static_assert(DBL_MANT_DIG == 53 && DBL_MAX_EXP == 1024, "IEEE-754 binary64 required");
#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "This demo decodes KLEE tests as little-endian binary64"
#endif
#include "guard.inc"

int main(void)
{
    double a0;
    uint64_t bits;
    klee_make_symbolic(&a0, sizeof a0, "a0");
    memcpy(&bits, &a0, sizeof bits);
    /* Positive IEEE-754 binary64 encodings are ordered as unsigned integers. */
    klee_assume(bits >= UINT64_C(0x4000000000000000)); /* 2 */
    klee_assume(bits <= UINT64_C(0x4018000000000000)); /* 6 */
    int outcome = trig_branch(a0);
#ifdef DEMO_REPLAY
    printf("GORDIAN_TRIG x=%.17g outcome=%d\n", a0, outcome);
#endif
    return 0;
}
