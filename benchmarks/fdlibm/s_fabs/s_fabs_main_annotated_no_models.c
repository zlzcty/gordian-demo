#include "fdlibm.h"
#include <klee/klee.h>

/* @(#)s_fabs.c 1.3 95/01/18 */
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
 * fabs(x) returns the absolute value of x.
 */

#ifdef __STDC__
	double fabs(double x)
#else
	double fabs(x)
	double x;
#endif
{
	__HI(x) &= 0x7fffffff;
        return x;
}

int main() {
    double a0;
    klee_make_symbolic(&a0, sizeof(a0), "a0");

    double r = fabs(a0);
    return 0;
}
