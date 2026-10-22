#include <stdio.h>
#include "utils.h"
#include "../../assume.h"

#include "a_tester.h"

assume_NL_start;
#define jmp(addr) asm("jmp *%0"::"r"(addr):)

// {"s":{"length": 4}}
int logic_bomb(char* s) {
    int symvar = s[0] - 48;
    if (symvar%6 != 1 || symvar < 10|| symvar > 40 || symvar == 19)
	symvar = 13;
    long long addr = &&flag_0 + symvar;
    jmp(addr);
  flag_0:
    if (symvar > 0){
        symvar++;
        if(symvar == 0)
            return BOMB_ENDING;
    }
    return NORMAL_ENDING;
}
assume_NL_stop;