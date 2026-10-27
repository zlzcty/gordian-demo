/*
 * harness_part3.c -- semantic partition 3: string-length shapes and non-digit first bytes.
 *
 * Family: the string shape is varied, i.e. where the NUL terminator sits and what
 * the first byte is (empty string, one-character string, leading space,
 * high-bit byte, '/'). Terminators are placed concretely; the other bytes stay
 * symbolic and are only constrained where the shape needs it.
 *
 * Why: logic_bomb() reads s[0] only, so the shape changes which bytes are
 * live, not the arithmetic. This partition covers the short-string and
 * negative-symvar paths that the pinned-digit partition does not reach.
 * The UNCOVERED branch (line 13) is reached by the one-character string "7".
 *
 * Assumptions:
 *  - The precondition s[4] == '\0' from the original main is kept in every case.
 *  - Concrete writes to s[1..2] (terminators) are plain C stores into the symbolic buffer.
 *  - High-bit first bytes are tested with (unsigned char) so the test does not depend on char signedness.
 *  - BOMB_ENDING / NORMAL_ENDING come from a_tester.h (same include path).
 */
#include <klee/klee.h>
#include "a_tester.h"

extern int logic_bomb(char* s);

int main(int argc, char **argv) {
    char s[5];
    klee_make_symbolic(s, sizeof s, "s");
    klee_assume(s[4] == '\0');

    int klass = klee_range(0, 5, "klass");
    int r = NORMAL_ENDING;
    switch (klass) {
    case 0: /* empty string: s[0] == NUL, symvar -48, all bytes after it terminated */
        s[0] = '\0';
        s[1] = '\0';
        s[2] = '\0';
        s[3] = '\0';
        break;
    case 1: /* one-character string "7": terminator at s[1], bomb through a short string */
        klee_assume(s[0] == '7');
        s[1] = '\0';
        break;
    case 2: /* "/" followed by a non-empty symbolic byte, terminator at s[2] */
        klee_assume(s[0] == '/');
        klee_assume(s[1] != '\0');
        s[2] = '\0';
        break;
    case 3: /* high-bit first byte (negative symvar on signed-char targets), terminator at s[1] */
        klee_assume((unsigned char)s[0] >= 0x80);
        s[1] = '\0';
        break;
    case 4: /* leading space then '7': only s[0] is read, so NORMAL_ENDING */
        klee_assume(s[0] == ' ');
        klee_assume(s[1] == '7');
        s[2] = '\0';
        break;
    default:
        klee_silent_exit(0);
    }
    r = logic_bomb(s);
    return r;
}
