/*
 * harness_part2.c -- semantic partition 2: integer-domain bisection of a symbolic digit.
 *
 * Family: a symbolic digit is chosen with klee_choose and then split with plain
 * integer comparisons in the harness. Each leaf calls logic_bomb with
 * s[0] = '0' + d (or the concrete '7' in the equality leaf). The split is done
 * in integer arithmetic, so each path carries a narrow range for d, and the
 * float concretisation inside logic_bomb picks one value per leaf.
 * Only symvar == 7 satisfies the float test (7/70.0 == 0.1), so the bomb leaf
 * is the one that probes '7'.
 *
 * Assumptions:
 *  - Only s[0] matters to logic_bomb; the rest of s stays symbolic.
 *  - The precondition s[4] == '\0' from the original main is kept.
 *  - klee_choose(name, lo, hi) is inclusive (klee_extra.h).
 *  - Symbolic names are distinct: "klass", "d0", "d1", "d2", "s".
 */
#include <klee/klee.h>
#include "klee_extra.h"
#include "a_tester.h"

extern int logic_bomb(char* s);

/* write one candidate first byte and run the function under test */
static int p2_probe(char *s, int c) {
    s[0] = (char)c;
    return logic_bomb(s);
}

int main(int argc, char **argv) {
    char s[5];
    klee_make_symbolic(s, sizeof s, "s");
    klee_assume(s[4] == '\0');

    int klass = klee_range(0, 3, "klass");
    int r = NORMAL_ENDING;
    switch (klass) {
    case 0: { /* full digit window, bisect around 7 */
        int d0 = klee_choose("d0", 0, 9);
        if (d0 < 7)
            r = p2_probe(s, '0' + d0);
        else if (d0 == 7)
            r = p2_probe(s, '7');     /* bomb leaf */
        else
            r = p2_probe(s, '0' + d0);
        break;
    }
    case 1: { /* threshold neighbourhood only: window 5..9, same split at 7 */
        int d1 = klee_choose("d1", 5, 9);
        if (d1 < 7)
            r = p2_probe(s, '0' + d1);
        else if (d1 == 7)
            r = p2_probe(s, '7');     /* bomb leaf */
        else
            r = p2_probe(s, '0' + d1);
        break;
    }
    case 2: { /* no ordering: a single equality probe on the threshold digit */
        int d2 = klee_choose("d2", 0, 9);
        if (d2 == 7)
            r = p2_probe(s, '7');     /* bomb leaf */
        else
            r = p2_probe(s, '0' + d2);
        break;
    }
    default:
        klee_silent_exit(0);
    }
    return r;
}
