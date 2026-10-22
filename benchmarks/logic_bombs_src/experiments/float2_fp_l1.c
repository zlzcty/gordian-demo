#include<stdio.h>
#include <stdlib.h>
#include "a_tester.h"
#include "../../assume.h"


// {"s":{"length": 4}}
int logic_bomb(char* s) {
    assume_NL_start;
    int symvar = s[0] - 48;
    float x = symvar + 0.0000005;
    if(x != 7){
        float x = symvar + 1;
        if (x == 8)
            return BOMB_ENDING;
    }
    return NORMAL_ENDING;
    assume_NL_stop; 
}
