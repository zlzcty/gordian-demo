/*
TOY:
*/
#include <string.h> 
#include <math.h>
#include "utils.h"
#include "a_tester.h"
#include "../../assume.h"


// {"s":{"length": 4}}
int logic_bomb(char* s) {
    assume_NL_start;
    int symvar = s[0] - 48;
    double d = log(symvar);
    assume_NL_stop; 
    if(1.94 < d && d < 1.95){
        return BOMB_ENDING;
    }else{
        return NORMAL_ENDING;
    }
}
