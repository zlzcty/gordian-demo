#include <klee/klee.h>

extern int logic_bomb(char* s);

/* Decimal leading bytes; the three trailing bytes remain decimal digits.
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
    klee_make_symbolic(s, sizeof s, "p1_s");
    klee_assume(s[4] == '\0');
    klee_assume(s[1] >= 48);
    klee_assume(s[1] <= 57);
    klee_assume(s[2] >= 48);
    klee_assume(s[2] <= 57);
    klee_assume(s[3] >= 48);
    klee_assume(s[3] <= 57);

    switch (klass) {
    case 0: s[0] = 48; break; /* zero */
    case 1: s[0] = 49; break; /* small positive fraction */
    case 2: s[0] = 54; break; /* below the target */
    case 3: s[0] = 55; break; /* target: symvar = 7 */
    case 4: s[0] = 56; break; /* above the target */
    case 5: s[0] = 57; break; /* largest decimal digit */
    default: klee_silent_exit(0); return 0;
    }
    return logic_bomb(s);
}
