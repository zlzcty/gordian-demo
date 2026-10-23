MOCK REHEARSAL RESPONSE — prewritten fixture, not output from a live model.

<<<FILE guard.inc>>>
/* MOCK REHEARSAL surrogate. The fixed driver already restricts x to [2, 6].
 * Keep [2, 3] (negative sin*cos) and [4, 4.5] (positive sin*cos), away from
 * the zeros at pi and 3*pi/2. Integer comparisons avoid symbolic FP. */
static int trig_branch(double x)
{
    uint64_t bits;
    memcpy(&bits, &x, sizeof bits);
    const uint64_t three = UINT64_C(0x4008000000000000);
    const uint64_t four = UINT64_C(0x4010000000000000);
    const uint64_t four_half = UINT64_C(0x4012000000000000);
    klee_assume((bits <= three) | ((bits >= four) & (bits <= four_half)));
    if (bits <= three) return 1;
    return 2;
}
<<<END FILE>>>
<<<FILE notes.md>>>
This is a PREWRITTEN MOCK for rehearsing the infrastructure, not a model result.

On [2, 3], sine is positive and cosine negative, so the product is negative.
On [4, 4.5], both are negative, so the product is positive. Both intervals
are safely away from zeros. The original driver's domain makes the lower
bound 2 implicit. Positive binary64 encodings sort as unsigned integers.
The surrogate intentionally restricts exploration to those two intervals;
it is not an equivalent implementation on the entire original domain.
KLEE must find the inputs, and replay through the ORIGINAL FDLibM code must
establish the branch outcome. No test case is injected into the runner.
<<<END FILE>>>
