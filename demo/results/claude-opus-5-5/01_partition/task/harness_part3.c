/* Harness part 3: string-shape partitioning with the first char fixed.
 * Assumptions: only s[0] matters for the uncovered line (s[0]=='7'); the
 * remaining bytes are shaped into different string families (digit string,
 * short string with early NUL, arbitrary bytes, negative/high chars) to give
 * complementary configurations. s[0] is always concrete so the float
 * computation runs on concrete data. */
#include <klee/klee.h>

extern int logic_bomb(char *s);

int main(int argc, char **argv) {
    char s[5];
    int i;
    int klass = klee_range(0, 5, "klass");
    klee_make_symbolic(s, sizeof s, "s");
    klee_assume(s[4] == '\0');
    switch (klass) {
    case 0: /* "7ddd": numeric string starting with 7 */
        s[0] = '7';
        for (i = 1; i < 4; i++) klee_assume(s[i] >= '0' && s[i] <= '9');
        break;
    case 1: /* "7" with early terminator */
        s[0] = '7';
        s[1] = '\0';
        break;
    case 2: /* '7' followed by arbitrary bytes */
        s[0] = '7';
        break;
    case 3: /* high-bit char: negative symvar */
        s[0] = (char)-56;
        break;
    default: /* empty string */
        s[0] = '\0';
        break;
    }
    return logic_bomb(s);
}
