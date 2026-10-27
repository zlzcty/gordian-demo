/* Harness part 2: integer-forked enumeration of a symbolic first char.
 * Assumptions: target needs s[0]=='7' (only solution of the float condition).
 * s[0] is symbolic but restricted per case to a small integer window; an
 * integer loop forks one path per value and writes the CONCRETE value back,
 * so the float code in logic_bomb never sees a symbolic operand (avoids
 * "silently concretizing"). Family: printable-character windows. */
#include <klee/klee.h>

extern int logic_bomb(char *s);

static void concretize_first(char *s, int lo, int hi) {
    int v;
    klee_assume(s[0] >= lo && s[0] <= hi);
    for (v = lo; v <= hi; v++) {
        if (s[0] == v) { s[0] = (char)v; return; }
    }
}

int main(int argc, char **argv) {
    char s[5];
    int klass = klee_range(0, 4, "klass");
    klee_make_symbolic(s, sizeof s, "s");
    klee_assume(s[4] == '\0');
    switch (klass) {
    case 0: concretize_first(s, '4', '9'); break; /* window holding '7' */
    case 1: concretize_first(s, '0', '3'); break; /* low digits */
    case 2: concretize_first(s, 'a', 'f'); break; /* letters: large symvar */
    default: concretize_first(s, ' ', '/'); break; /* punctuation: negative symvar */
    }
    return logic_bomb(s);
}
