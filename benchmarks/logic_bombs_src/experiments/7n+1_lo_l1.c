#include <string.h> 
#include "utils.h"
#include "a_tester.h"
#include "../../assume.h"

long f(long x){
    if (x%2 == 0)
	return x/2;
    else if (x%3 == 0)
	return x/3;
    else if (x%5 == 0)
	return x/5;
    else
        return 7*x + 1;
}

// {"s":{"length": 4}}
int logic_bomb(char* s) {
    int symvar = s[0] - 48;
    symvar = symvar + 1104;
    long j = f(symvar);
    int loopcount = 1;
    assume_NL_start;
    while(j != 1){
	j = f(j);
        loopcount ++;
    }
    assume_NL_stop;
    if(loopcount == 50)
        return BOMB_ENDING;
    else
        return NORMAL_ENDING;
}
