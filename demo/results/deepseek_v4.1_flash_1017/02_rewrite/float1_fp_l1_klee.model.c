#include <klee/klee.h>
#include<stdio.h>
#include <stdlib.h>
#include "a_tester.h"

typedef union {
    float f;
    uint64_t u;
} float_uint;

int logic_bomb(char* s) {
    int symvar = s[0] - 48;
    float_uint fu;
    fu.u = 0;
    memcpy(&fu.u, &symvar, sizeof(int));
    float a = fu.f / 70.0;
    float b = 0.1;
    if(a != 0.1){
	if((fu.u & 0xFFFFFFFF00000000) == 0x3F80000000000000) { // a == 0.1
            if((fu.u & 0xFFFFFFFFFFFFFFFF) == 0x3CA3D70A3D70A3D7) { // a - b == 0
                return BOMB_ENDING;
            }
        }
    }
    return NORMAL_ENDING;
}

int main(int argc, char** argv) {
char s[5];
klee_make_symbolic(&s, sizeof(s), "s");
klee_assume(s[4]=='\0');
return logic_bomb(s);
}
