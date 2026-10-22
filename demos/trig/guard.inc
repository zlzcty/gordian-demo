/* Reduced from benchmarks/fdlibm_lib/e_j0.c, __ieee754_j0.
 * Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
 * Developed at SunSoft, a Sun Microsystems, Inc. business.
 * Permission to use, copy, modify, and distribute this software is freely
 * granted, provided that this notice is preserved.
 *
 * Teaching adaptation: retain the branch predicates, remove Bessel output
 * calculations, and return distinct outcomes. Use memcpy for bit access.
 * sin/cos are external libm calls, not linked FDLibM implementations.
 */
static int trig_branch(double x)
{
    uint64_t bits;
    memcpy(&bits, &x, sizeof bits);
    uint32_t ix = (uint32_t)(bits >> 32) & UINT32_C(0x7fffffff);
    if (ix >= UINT32_C(0x7ff00000)) return 0;
    bits &= UINT64_C(0x7fffffffffffffff);
    memcpy(&x, &bits, sizeof x); /* fabs without a symbolic FP operation */
    if (ix >= UINT32_C(0x40000000)) {
        double s = sin(x);
        double c = cos(x);
        if (ix < UINT32_C(0x7fe00000)) {
            if (s * c < 0.0) return 1; /* negative product */
            return 2;                 /* nonnegative product */
        }
    }
    return 0;
}
