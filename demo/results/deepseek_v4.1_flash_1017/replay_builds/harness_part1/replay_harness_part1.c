#include <klee/klee.h>

extern int logic_bomb(char* s);

int main(int argc, char **argv) {
    (void)argc;
    (void)argv;

    int klass = klee_range(0, 4, "klass");
    switch (klass) {
        case 0: {
            char s[5];
            klee_make_symbolic(s, sizeof s, "p1_s0");
            s[0] = '7';
            s[4] = '\0';
            return logic_bomb(s);
        }
        case 1: {
            char s[5];
            klee_make_symbolic(s, sizeof s, "p1_s1");
            s[0] = '0';
            s[4] = '\0';
            return logic_bomb(s);
        }
        case 2: {
            char s[5];
            klee_make_symbolic(s, sizeof s, "p1_s2");
            s[0] = '9';
            s[4] = '\0';
            return logic_bomb(s);
        }
        case 3: {
            char s[5];
            klee_make_symbolic(s, sizeof s, "p1_s3");
            s[0] = '5';
            s[4] = '\0';
            return logic_bomb(s);
        }
        default:
            return 0;
    }
}
