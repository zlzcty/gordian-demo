/* Harness part 1: concrete-digit partitioning.
 * Assumptions: the only uncovered line needs (float)((s[0]-48)/70.0) == 0.1f,
 * which holds only for s[0]=='7' (checked by brute force over all chars).
 * Standard KLEE concretizes the symbolic float division, so each case fixes
 * s[0] to a CONCRETE digit (FP then runs on concrete values) while s[1..3]
 * stay symbolic. Family: decimal digits '0'..'9' around the target. */
#include <klee/klee.h>

extern int logic_bomb(char *s);

int main(int argc, char **argv) {
    char s[5];
    int klass = klee_range(0, 6, "klass"); // choose a class of input to concretize the first character of s
    // ^ semantic partitioning: 6 classes of first char, each with a different concrete value

    klee_make_symbolic(s, sizeof s, "s"); // make the input string symbolic
    klee_assume(s[4] == '\0'); // assume that the last character of the string is null terminator

    switch (klass) {
        case 0: s[0] = '7'; break;   /* bomb: 7/70 rounds to 0.1f */
        case 1: s[0] = '0'; break;   /* a == 0 */
        case 2: s[0] = '6'; break;   /* just below */
        case 3: s[0] = '8'; break;   /* just above */
        case 4: s[0] = '1'; break;
        default: s[0] = '9'; break;
    }
    return logic_bomb(s);
}
