#include <klee/klee.h>
#include <string.h> 
#include "utils.h"
// #include "a_tester.h"

int n = 5;

// {"symvar":{"length": 256}}
int logic_bomb(char* symvar) {
    char *p, *q;
    p = (char*)malloc(16);
    q = (char*)malloc(16);
    strcpy(p, symvar);
    free(q);
    if (n != 5){
        free(p);
        klee_assert(0 && "Logic bomb triggered");
        return 1;
    }else {
        free(p);
        return 0;
    }
}

int main(int argc, char** argv) {
char symvar[257];
klee_make_symbolic(&symvar, sizeof(symvar), "symvar");
klee_assume(symvar[256]=='\0');
return logic_bomb(symvar);
}
