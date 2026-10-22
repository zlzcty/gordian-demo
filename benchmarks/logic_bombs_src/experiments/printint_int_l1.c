/*
TOY:
Solution: 7
*/
#include <string.h> 
#include "utils.h"
#include "a_tester.h"
#include "../../assume.h"
// {"s":{"length": 4}}
int logic_bomb(char* s) {
    assume_NL_start;
    int symvar = s[0] - 48;
    int x = symvar + 190;
    printf("x = %d\n", x);
    assume_NL_stop;
    if(x == 197){
        return BOMB_ENDING;
    }else{
        return NORMAL_ENDING;
    }
}
