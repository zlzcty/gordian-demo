#include <string.h> 
#include "utils.h"
#include "../../assume.h"
#include "a_tester.h"

// {"s":{"length": 16}}
int logic_bomb(char* s) {
    assume_NL_start;
    int trigger = 0;
    int fd = open(s, O_RDONLY);
    if(fd != -1) {
    	trigger = 1;
        close(fd);
    }
    assume_NL_stop;

    if(trigger) {
        return BOMB_ENDING;
    } else {
        return NORMAL_ENDING;
    }
}
