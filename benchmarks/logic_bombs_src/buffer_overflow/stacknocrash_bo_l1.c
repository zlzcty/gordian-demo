#include <string.h> 
#include "utils.h"
#include "a_tester.h"
#include "../../assume.h"


// {"symvar":{"length": 64}}
int logic_bomb(char* symvar) {
    int flag = 0;
    char buf[8];
    if(strlen(symvar) > 9)
        return NORMAL_ENDING;
    assume_NL_start;
    strcpy(buf, symvar);
    assume_NL_stop;
    if(flag == 1){
        return BOMB_ENDING;
    }
    return NORMAL_ENDING;
}
