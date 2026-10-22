#include <klee/klee.h>
/*
TOY:
Solution: 30
*/
#include <string.h> 
#include <math.h>
#include "utils.h"

#define PI 3.14159265358979323846264338327

#include "a_tester.h"

// {"s":{"length": 4}}
int logic_bomb(char* s) {
    int symvar = s[0];
    float v = sin(symvar*PI/30);
    if(v > 0.5){
        return BOMB_ENDING;
    }else{
        return NORMAL_ENDING;
    }
}

int main(int argc, char** argv) {
char s[5];
klee_make_symbolic(&s, sizeof(s), "s");
klee_assume(s[4]=='\0');
return logic_bomb(s);
}
