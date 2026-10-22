#include "a_tester.h"
#include "../../assume.h"

// {"s":{"length": 4}}
int logic_bomb(char* s) {
    assume_NL_start;
    int symvar = s[0] - 48;
    if (254748364 * symvar < 0 && symvar > 0)
        return BOMB_ENDING;
    else
        return NORMAL_ENDING;
    assume_NL_stop;
}
