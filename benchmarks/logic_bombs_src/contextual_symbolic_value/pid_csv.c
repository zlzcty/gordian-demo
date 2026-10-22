#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#include "a_tester.h"
#include "../../assume.h"

// {"s":{"length": 4}}
int logic_bomb(char* s) {
   assume_NL_start;
   int symvar = s[0] - 48;
   int pid = (int) getpid();
   assume_NL_stop
   if(pid%78 == symvar)
    return BOMB_ENDING;
   else
    return NORMAL_ENDING;
}
