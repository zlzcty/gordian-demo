/*
 * harness_part1.c -- semantic partition 1: pinned first-byte classes.
 *
 * Family: s[0] is pinned per case to one concrete representative of a class:
 * the bomb digit '7', its neighbours '0', '6', '8', and a non-digit just below
 * '0' ('/'). The tail s[1..3] stays symbolic, restricted to digits.
 *
 * Why: logic_bomb() computes symvar = s[0] - 48 and then does floating point
 * on it (symvar/70.0, compared with 0.1). KLEE concretises floating-point
 * operands silently, so a symbolic s[0] only ever yields one value per path.
 * Pinning the class here makes each path's value explicit. The UNCOVERED
 * branch (return BOMB_ENDING, line 13) needs symvar == 7 exactly, i.e. s[0] == '7'.
 *
 * Assumptions:
 *  - logic_bomb reads only s[0]; the tail is kept symbolic but cannot change the result.
 *  - The precondition s[4] == '\0' from the original main is kept.
 *  - BOMB_ENDING / NORMAL_ENDING come from a_tester.h (same include path).
 */
#include <klee/klee.h>
#include "a_tester.h"

extern int logic_bomb(char* s);

/* symbolic digit tail: s[1..3] in '0'..'9' */
static void p1_digit_tail(char *s) {
    klee_assume(s[1] >= '0' && s[1] <= '9');
    klee_assume(s[2] >= '0' && s[2] <= '9');
    klee_assume(s[3] >= '0' && s[3] <= '9');
}

int main(int argc, char **argv) {
    char s[5];
    klee_make_symbolic(s, sizeof s, "s");
    klee_assume(s[4] == '\0');

    int klass = klee_range(0, 5, "klass");
    int r = NORMAL_ENDING;
    switch (klass) {
    case 0: /* bomb target: symvar == 7, so (float)(7/70.0) == 0.1f */
        klee_assume(s[0] == '7');
        break;
    case 1: /* '0': symvar 0, a == 0 */
        klee_assume(s[0] == '0');
        break;
    case 2: /* '6': symvar 6, just below the threshold */
        klee_assume(s[0] == '6');
        break;
    case 3: /* '8': symvar 8, just above the threshold */
        klee_assume(s[0] == '8');
        break;
    case 4: /* '/': symvar -1, below the digit range */
        klee_assume(s[0] == '/');
        break;
    default:
        klee_silent_exit(0);
    }
    p1_digit_tail(s);
    r = logic_bomb(s);
    return r;
}
