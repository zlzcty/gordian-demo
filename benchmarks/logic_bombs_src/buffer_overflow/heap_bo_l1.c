#include <string.h> 
#include "utils.h"
#include "a_tester.h"
#include "../../assume.h"

int n = 5;

// {"symvar":{"length": 256}}
int logic_bomb(char* symvar) {
    assume_NL_start;
    char *p, *q;
    p = (char*)malloc(16);
    q = (char*)malloc(16);
    strcpy(p, symvar);
    free(q);
    assume_NL_stop;
    if (n != 5){
        free(p);
        return BOMB_ENDING;
    }else {
        free(p);
        return NORMAL_ENDING;
    }
    
}
