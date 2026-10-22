#include <klee/klee.h>
#include<stdio.h>
#include <stdlib.h>
#include "a_tester.h"

// {"s":{"length": 8}}
int logic_bomb(char* symvar) {
    float x = atof(symvar);
    x = x/10.0;
    x = x + 0.1;
    x = x * x;
    if (x > 0.1)
	x -= x;
    if(x != 0.02){
        x = x + 7.98;
        if(x == 8)
            return BOMB_ENDING;
    }
    return NORMAL_ENDING;
}

int main(int argc, char** argv) {
char symvar[9];
klee_make_symbolic(&symvar, sizeof(symvar), "symvar");
klee_assume(symvar[8]=='\0');
return logic_bomb(symvar);
}
