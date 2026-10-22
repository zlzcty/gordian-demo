#include <klee/klee.h>
#include <string.h> 
#include "utils.h"

#include "a_tester.h"

// {"s":{"length": 16}}
int logic_bomb(char* s) {
    int trigger = 0;
    int fd = open(s, O_RDONLY);
    if(fd != -1) {
    	trigger = 1;
        close(fd);
    }

    if(trigger) {
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
