#include <klee/klee.h>
#include "fdlibm.h"

/* @(#)s_matherr.c 1.3 95/01/18 */
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

#ifdef __STDC__
	int matherr(struct exception *x)
#else
	int matherr(x)
	struct exception *x;
#endif
{
	int n=0;
	if(x->arg1!=x->arg1) return 0;
	return n;
}

int main() {
    struct exception ex;
    klee_make_symbolic(&ex, sizeof(ex), "ex");
    int r = matherr(&ex);
    return 0;
}
