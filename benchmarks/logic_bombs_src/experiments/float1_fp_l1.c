#include<stdio.h>
#include <stdlib.h>
#include "a_tester.h"
#include "../../assume.h"
// {"s":{"length": 4}}
int logic_bomb(char* s) {
    assume_NL_start;
    int symvar = s[0] - 48;
    float a = symvar/70.0;
    float b = 0.1;
    if(a != 0.1){
	if(a - b == 0)
            return BOMB_ENDING;
    }
    return NORMAL_ENDING;
    assume_NL_stop;
}
