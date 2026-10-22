#include "fdlibm.h"
#include <klee/klee.h>

/* @(#)s_significand.c 1.3 95/01/18 */
/*
 * ====================================================
 * Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
 *
 * Developed at SunSoft, a Sun Microsystems, Inc. business.
 * Permission to use, copy, modify, and distribute this
 * software is freely granted, provided that this notice 
 * is preserved.
 * ====================================================
 */

/*
 * significand(x) computes just
 * 	scalb(x, (double) -ilogb(x)),
 * for exercising the fraction-part(F) IEEE 754-1985 test vector.
 */

#ifdef __STDC__
	double significand(double x)
#else
	double significand(x)
	double x;
#endif
{
	return __ieee754_scalb(x,(double) -ilogb(x));
}

int main() {
    int lib_version_sel = klee_range(0, 4, "lib_version_sel");
    switch (lib_version_sel) {
        case 0: _LIB_VERSION = _IEEE_;  break;
        case 1: _LIB_VERSION = _SVID_;  break;
        case 2: _LIB_VERSION = _XOPEN_; break;
        case 3: _LIB_VERSION = _POSIX_; break;
    }

    double a0;
    klee_make_symbolic(&a0, sizeof(a0), "a0");

    double r = significand(a0);
    return 0;
}
