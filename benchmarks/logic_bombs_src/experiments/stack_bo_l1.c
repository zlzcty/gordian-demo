#include <string.h> 
#include "utils.h"
#include "a_tester.h"
#include "../../assume.h"


// {"symvar":{"length": 64}}
int logic_bomb(char* symvar) {
    assume_NL_start;
    int flag = 0;
    char buf[8];
    strcpy(buf, symvar);
    assume_NL_stop;
    if(flag == 1){
        return BOMB_ENDING;
    }
    return NORMAL_ENDING;

}
