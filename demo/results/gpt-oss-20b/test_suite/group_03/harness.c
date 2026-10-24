#include <klee/klee.h>

extern int logic_bomb(char* s);

int main(int argc, char **argv) {
    int klass = klee_range(0, 4, "klass");
    char s[5];
    s[4] = '\0';

    switch (klass) {
        case 0:
            s[0] = '6';
            break;
        case 1:
            s[0] = '7';
            break;
        case 2:
            s[0] = '8';
            break;
        case 3:
            s[0] = '9';
            break;
    }

    s[1] = s[2] = s[3] = 0;
    return logic_bomb(s);
}
