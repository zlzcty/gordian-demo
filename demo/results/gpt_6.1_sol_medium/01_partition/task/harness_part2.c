#include <klee/klee.h>

extern int logic_bomb(char* s);

/* Control, whitespace and punctuation leading bytes; printable symbolic tails.
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
    klee_make_symbolic(s, sizeof s, "p2_s");
    klee_assume(s[4] == '\0');
    klee_assume(s[1] >= 32);
    klee_assume(s[1] <= 126);
    klee_assume(s[2] >= 32);
    klee_assume(s[2] <= 126);
    klee_assume(s[3] >= 32);
    klee_assume(s[3] <= 126);

    switch (klass) {
    case 0: s[0] = 0; break; /* embedded NUL: symvar = -48 */
    case 1: s[0] = 32; break; /* space: negative fraction */
    case 2: s[0] = 45; break; /* minus punctuation: symvar = -3 */
    case 3: s[0] = 46; break; /* dot punctuation: symvar = -2 */
    case 4: s[0] = 47; break; /* slash: immediately below zero */
    case 5: s[0] = 55; break; /* target anchor: symvar = 7 */
    default: klee_silent_exit(0); return 0;
    }
    return logic_bomb(s);
}
