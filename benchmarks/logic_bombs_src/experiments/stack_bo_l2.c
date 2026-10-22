#include <string.h> 
#include "utils.h"
#include "a_tester.h"
#include "../../assume.h"

int trigger(){
    return BOMB_ENDING;
}

// {"symvar":{"length": 128}}
int logic_bomb(char* symvar) {
    assume_NL_start;
    char buf[8];
    strcpy(buf, symvar);
    assume_NL_stop;
    if(buf < 0)
        return trigger();
    return NORMAL_ENDING;
}
