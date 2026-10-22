#include <string.h> 
#include "utils.h"

#include "a_tester.h"
#include "../../assume.h"

// {"s":{"length": 16}}
int logic_bomb(char* s) {
    assume_NL_start
    int trigger = 0;
    FILE *fp = fopen(s, "r");
    if(fp != NULL) {
	trigger = 1;
        fclose(fp);
    }
    assume_NL_stop;

    if(trigger) {
        return BOMB_ENDING;
    } else {
        return NORMAL_ENDING;
    }
}
