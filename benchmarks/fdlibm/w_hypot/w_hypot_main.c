
/* @(#)w_hypot.c 1.3 95/01/18 */
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
 * wrapper hypot(x,y)
 */

#include "fdlibm.h"


#ifdef __STDC__
	double hypot(double x, double y)/* wrapper hypot */
#else
	double hypot(x,y)		/* wrapper hypot */
	double x,y;
#endif
{
#ifdef _IEEE_LIBM
	return __ieee754_hypot(x,y);
#else
	double z;
	z = __ieee754_hypot(x,y);
	if(_LIB_VERSION == _IEEE_) return z;
	if((!finite(z))&&finite(x)&&finite(y))
	    return __kernel_standard(x,y,4); /* hypot overflow */
	else
	    return z;
#endif
}
#include <klee/klee.h>

int main() {
    double a0;
    klee_make_symbolic(&a0, sizeof(a0), "a0");
    double a1;
    klee_make_symbolic(&a1, sizeof(a1), "a1");

    double r = hypot(a0, a1);
    return 0;
}
