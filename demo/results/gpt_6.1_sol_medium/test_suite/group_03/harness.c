#include <klee/klee.h>

extern int logic_bomb(char* s);

/* Larger positive numerators and the ASCII upper boundary; nonzero ASCII tails.
 * Assumptions: ASCII bytes and ordinary IEEE-754 binary32/binary64 C
 * evaluation without fast-math. Only s[0] is read by logic_bomb.
 * Each case fixes that byte before any floating-point operation, avoiding
 * symbolic FP concretization in standard KLEE. The whole writable array
 * is made symbolic once; its unused trailing bytes retain bounded freedom.
 * Byte 55 gives a == b as floats, so a-b == 0, while promoted a differs
 * from the double literal 0.1. That case reaches the UNCOVERED return.
 * The target anchor intentionally overlaps the complementary families.
 */
int main(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    char s[5];
    int klass = klee_range(0, 6, "klass");
    klee_make_symbolic(s, sizeof s, "p3_s");
    klee_assume(s[4] == '\0');
    klee_assume(s[1] >= 1);
    klee_assume(s[1] <= 127);
    klee_assume(s[2] >= 1);
    klee_assume(s[2] <= 127);
    klee_assume(s[3] >= 1);
    klee_assume(s[3] <= 127);

    switch (klass) {
    case 0: s[0] = 55; break; /* target anchor: symvar = 7 */
    case 1: s[0] = 58; break; /* first byte above the decimal digits */
    case 2: s[0] = 65; break; /* alphabetic leading byte */
    case 3: s[0] = 70; break; /* larger positive fraction */
    case 4: s[0] = 118; break; /* exact unit quotient: symvar = 70 */
    case 5: s[0] = 127; break; /* largest nonnegative ASCII byte */
    default: klee_silent_exit(0); return 0;
    }
    return logic_bomb(s);
}
