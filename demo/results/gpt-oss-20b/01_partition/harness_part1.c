#include <klee/klee.h>

extern int logic_bomb(char* s);

int main(int argc, char **argv) {
    int klass = klee_range(0, 3, "klass");
    char s[5];
    s[4] = '\0';

    switch (klass) {
        case 0:
            s[0] = '0';
            break;
        case 1:
            s[0] = '1';
            break;
        case 2:
            s[0] = '2';
            break;
    }

    s[1] = s[2] = s[3] = 0;
    return logic_bomb(s);
}
