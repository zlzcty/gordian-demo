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
    klee_assume(s[0] >= lo && s[0] <= hi); // assume that the first character of the string is within the range [lo, hi]
    for (v = lo; v <= hi; v++) { // loop over the range [lo, hi]
        if (s[0] == v) { s[0] = (char)v; return; } // if the first character of the string is equal to v, set it to the concrete value v and return
    }
}

int main(int argc, char **argv) {
    char s[5];
    int klass = klee_range(0, 4, "klass"); // choose a class of input to concretize the first character of s
    // ^ semantic partitioning: 4 classes of first char, each with a different concrete value

    klee_make_symbolic(s, sizeof s, "s"); // make the input string symbolic
    klee_assume(s[4] == '\0'); // assume that the last character of the string is null terminator
    // ^ assume that the input string is a null-terminated string

    switch (klass) {
    
        // the first character of the string is concretized to a value between '4' and '9', which includes '7'
        case 0: concretize_first(s, '4', '9'); break; /* window holding '7' */ 
        
        // the first character of the string is concretized to a value between '0' and '3', which are low digits
        case 1: concretize_first(s, '0', '3'); break; /* low digits */

        // the first character of the string is concretized to a value between 'a' and 'f', which are letters and result in a large symvar
        case 2: concretize_first(s, 'a', 'f'); break; /* letters: large symvar */

        // the first character of the string is concretized to a value between ' ' (space) and '/', 
        // which are punctuation characters and result in a negative symvar
        default: concretize_first(s, ' ', '/'); break; /* punctuation: negative symvar */
    }
    return logic_bomb(s);
}
