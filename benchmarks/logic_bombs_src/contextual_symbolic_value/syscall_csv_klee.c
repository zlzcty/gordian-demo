#include <klee/klee.h>
/*
TOY:
*/
#include <string.h>
#include "utils.h"

#include "a_tester.h"

// {"s":{"length": 16}}
int logic_bomb(char* s) {
    if(s == NULL)
	return NORMAL_ENDING;
    if(s[0]=='\0')
	return NORMAL_ENDING;
    int trigger = -1;
    trigger = system(s);
    if(trigger == 0) {
        return BOMB_ENDING;
    } else {
        return NORMAL_ENDING;
    }
}

int main(int argc, char** argv) {
char s[17];
klee_make_symbolic(&s, sizeof(s), "s");
klee_assume(s[16]=='\0');
return logic_bomb(s);
}
