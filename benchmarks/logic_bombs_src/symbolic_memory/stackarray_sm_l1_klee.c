#include <klee/klee.h>
#include<stdio.h>
#include"utils.h"
#include "a_tester.h"

// {"s":{"length": 4}}
int logic_bomb(char* s) {
    int symvar = s[0] - 48;
    int ary[] ={1,2,3,4,5};
    if(ary[symvar%5] == 5){
        return BOMB_ENDING;
     }
    else
	return NORMAL_ENDING;
}

int main(int argc, char** argv) {
char s[5];
klee_make_symbolic(&s, sizeof(s), "s");
klee_assume(s[4]=='\0');
return logic_bomb(s);
}
