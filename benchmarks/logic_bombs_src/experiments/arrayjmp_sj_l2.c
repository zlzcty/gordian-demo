#include <stdio.h>
#include "utils.h"
#include "a_tester.h"
#include "../../assume.h"
#define jmp(addr) asm("jmp *%0"::"r"(addr):)


assume_NL_start;
// {"s":{"length": 4}}
int logic_bomb(char* s) {
    int symvar = s[0] - 48;
    int array[] = {7,13,14,15,16,21,22,37,23,24};
    long long addr = &&flag_0 + array[symvar%10];
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