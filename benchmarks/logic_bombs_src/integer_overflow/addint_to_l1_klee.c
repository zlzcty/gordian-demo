#include <klee/klee.h>
#include "a_tester.h"

// {"s":{"length": 4}}
int logic_bomb(char* s) {
    int symvar = s[0] - 48;
    if (symvar + 2147483640 < 0 && symvar > 0)
        return BOMB_ENDING;
    else
        return NORMAL_ENDING;
}

int main(int argc, char** argv) {
char s[5];
klee_make_symbolic(&s, sizeof(s), "s");
klee_assume(s[4]=='\0');
return logic_bomb(s);
}
