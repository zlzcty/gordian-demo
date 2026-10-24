# FDLibM trigonometric branch demo

The target is the inner `if ((s*c) < zero)`. Most of the Bessel calculation can be removed while preserving the conditions that determine whether this branch is reached and which way it goes.

## Original benchmark

The complete original benchmark source is [e_j0_main_annotated_no_models.c](benchmarks/fdlibm/e_j0/e_j0_main_annotated_no_models.c). It contains `j0`, `y0`, polynomial tables, helper functions, and the symbolic-input harness. KLEE also receives the linked FDLibM sources listed in [fdlibm_e_j0.yaml](benchmarks/targets/fdlibm_e_j0.yaml); the benchmark file is not the entire linked program by itself.

The entire relevant `j0` function follows, with historical declaration syntax and comments simplified. Constants and helper functions remain defined elsewhere in the original file.

```c
double __ieee754_j0(double x)
{
    double z, s, c, ss, cc, r, u, v;
    int hx, ix;

    hx = __HI(x);
    ix = hx & 0x7fffffff;

    if (ix >= 0x7ff00000)
        return one / (x*x);

    x = fabs(x);

    if (ix >= 0x40000000) {       /* |x| >= 2.0 */
        s = sin(x);
        c = cos(x);

        ss = s-c;
        cc = s+c;

        if (ix < 0x7fe00000) {   /* Avoid overflow in x+x */
            z = -cos(x+x);

            if ((s*c) < zero)    /* TARGET GUARD */
                cc = z/ss;
            else
                ss = z/cc;
        }

        if (ix > 0x48000000) {
            z = (invsqrtpi*cc) / sqrt(x);
        } else {
            u = pzero(x);
            v = qzero(x);
            z = invsqrtpi*(u*cc - v*ss) / sqrt(x);
        }

        return z;
    }

    if (ix < 0x3f200000) {       /* |x| < 2^-13 */
        if (huge+x > one) {
            if (ix < 0x3e400000)
                return one;
            else
                return one - 0.25*x*x;
        }
    }

    z = x*x;
    r = z*(R02 + z*(R03 + z*(R04 + z*R05)));
    s = one + z*(S01 + z*(S02 + z*(S03 + z*S04)));

    if (ix < 0x3ff00000) {
        return one + z*(-0.25 + r/s);
    } else {
        u = 0.5*x;
        return (one+u)*(one-u) + z*(r/s);
    }
}
```

## Dependencies of the target guard

```text
symbolic x
    |
    +-- high bits of |x| --> conditions controlling reachability
    |
    +-- fabs(x) --> sin(x), cos(x) --> s*c < 0
```

The polynomial calculations, square roots, and final Bessel result do not influence the target guard. Neither do `ss`, `cc`, or `z`: those values are used in the branch bodies, but do not determine the branch decision.

## Complete reduced C harness

This harness preserves the target's controlling conditions and trigonometric calculation, and replaces the branch bodies with observable return values.

```c
#include <klee/klee.h>
#include <math.h>
#include <stdint.h>
#include <string.h>

/*
 * Demo assumption: double uses IEEE-754 binary64.
 *
 * Extract the high word without the original pointer-cast macro.
 */
static uint32_t high_word(double x)
{
    uint64_t bits;
    memcpy(&bits, &x, sizeof(bits));
    return (uint32_t)(bits >> 32);
}

/*
 * Return values:
 *   0: target guard was not reached
 *   1: target guard evaluated true
 *   2: target guard evaluated false
 *
 * This classifies the branch; it does not compute a Bessel function.
 */
static int trig_branch(double x)
{
    uint32_t ix = high_word(x) & UINT32_C(0x7fffffff);

    /* Original early exit for infinity and NaN. */
    if (ix >= UINT32_C(0x7ff00000))
        return 0;

    x = fabs(x);

    /* Original outer condition: |x| >= 2. */
    if (ix >= UINT32_C(0x40000000)) {
        double s = sin(x);
        double c = cos(x);

        /* Original condition protecting the x+x calculation. */
        if (ix < UINT32_C(0x7fe00000)) {
            if ((s*c) < 0.0)
                return 1;       /* Target's true branch */
            else
                return 2;       /* Target's false branch */
        }
    }

    return 0;
}

int main(void)
{
    double a0;
    klee_make_symbolic(&a0, sizeof(a0), "a0");

    return trig_branch(a0);
}
```

## What changed

| Removed or changed | Reason |
|---|---|
| `y0` and the symbolic `chooser` | Focuses the demo on the direct `j0` path. |
| Polynomial tables, `pzero`, `qzero`, and final calculations | They do not affect this guard. |
| `ss = s-c` and `cc = s+c` | Their values are only needed by the original branch bodies and later calculations. |
| `z = -cos(x+x)` | Its result does not affect the guard. Removal assumes ordinary execution without floating-point traps or relevant library side effects. |
| Original branch bodies | Replaced with distinct return values to expose the outcome. |
| `__HI(x)` | Replaced with explicit bit extraction for the binary64 demo. |

The crucial part remains unchanged: `sin` and `cos` consume the same `x`. Replacing them with independent symbolic values would be a further abstraction, rather than this dependency-based reduction.

## How a human solves the guard with mathematics

An expert can reason about the signs of sine and cosine without inspecting their implementations or computing inverse functions. The task is to find one input satisfying both the conditions needed to reach the target and the target predicate itself.

### 1. Translate the preceding guards into an input domain

For the intended IEEE-754 binary64 representation, `ix` is the high word of the input with its sign bit removed. The comparisons mean:

- `ix >= 0x7ff00000`: the input is infinity or NaN, which exits early.
- `ix >= 0x40000000`: the input magnitude is at least 2.
- `ix < 0x7fe00000`: the input magnitude is less than 2^1023.

After `x = fabs(x)`, reaching the target therefore requires:

\[
2 \le x < 2^{1023}.
\]

### 2. Recognize the sign pattern

The target condition is:

\[
\sin(x)\cos(x)<0.
\]

The product is negative when sine and cosine have opposite signs:

| Quadrant | Sine | Cosine | Product |
|---|---|---|---|
| I | Positive | Positive | Positive |
| II | Positive | Negative | Negative |
| III | Negative | Negative | Positive |
| IV | Negative | Positive | Negative |

Equivalently, apply the double-angle identity:

\[
\sin(x)\cos(x)=\tfrac12\sin(2x).
\]

Over the real numbers, the true-branch solution set is:

\[
x\in\bigcup_{k\in\mathbb Z}
\left(\frac{\pi}{2}+k\pi,\;\pi+k\pi\right).
\]

### 3. Intersect with the preceding constraints and choose a witness

The first suitable interval after applying the lower bound is:

\[
[2,\pi).
\]

Choose **`x = 2`**, an exactly representable double comfortably away from a trigonometric zero:

\[
\sin(2)\approx0.9093,\qquad
\cos(2)\approx-0.4161,
\]

so:

\[
\sin(2)\cos(2)\approx-0.3784<0.
\]

The original symbolic input `a0` can be either `2` or `-2`, because the function takes its absolute value. For comparison, `x = 4` is in quadrant III, where both sine and cosine are negative, so their product is positive and the target guard evaluates false.

### 4. Distinguish mathematical reasoning from concrete validation

The interval derivation uses exact real arithmetic. The program evaluates floating-point approximations to sine and cosine and rounds their product. Mathematical identities are useful for proposing witnesses, but do not establish exact equivalence between all floating-point expressions, particularly near zeros or underflow boundaries.

The proposed values `2` and `4` are away from those boundaries. Replaying them on the original implementation would confirm the branch outcomes; they have not been executed for this analysis.

For the presentation: **the human sees a quadrant constraint; the symbolic executor sees the instructions implementing a numerical library.** The LLM may recognize the mathematical shortcut, while KLEE's solver does not automatically assign trigonometric identities to library calls. Gordian attempts to supply a useful shortcut and then validate the resulting input through replay.

## Presentation task and verification status

The challenge is: **Generate an input reaching each of returns 1 and 2.** Analytically, `x = 2` should take the true branch and `x = 4` the false branch. These are illustrative witnesses, not executed results.

If comparing this harness with the original benchmark, use the same FDLibM trigonometric implementations so that changing the math library does not become another variable.

The reduced harness has not been built or run.
