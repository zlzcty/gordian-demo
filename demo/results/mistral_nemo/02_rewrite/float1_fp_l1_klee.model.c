```
#include <klee/klee.h>
#include<stdio.h>
#include <stdlib.h>
#include "a_tester.h"

// {"s":{"length": 4}}
int logic_bomb(char* s) {
    int symvar = s[0] - 48;
    uint64_t a_int = klee_choose(0, 100, "a_int");
    klee_assume(a_int % 70 == symvar);
    float a = *(float*)&a_int;
    float b = 0.1;
    if(a != 0.1){
        uint64_t diff_int = *(uint64_t*)&(a - b);
        if(diff_int == 0)
            return BOMB_ENDING;
    }
    return NORMAL_ENDING;
}

int main(int argc, char** argv) {
    char s[5];
    klee_make_symbolic(&s, sizeof(s), "s");
    klee_assume(s[4]=='\0');
    return logic_bomb(s);
}
