#include <klee/klee.h>
/*
*solution: 
*/
#include<stdio.h>
#include"utils.h"

#include "a_tester.h"

// {"s":{"length": 4}}
int logic_bomb(char* s) {
    int symvar = s[0] - 48;
    int i = symvar;
    int j = abs(i%11);
    int a[] = {(i+5)%11,(i+6)%11,(i+7)%11,(i+8)%11,(i+9)%11,(i+10)%11,i%11,(i+1)%11,(i+2)%11,(i+3)%11,(i+4)%11};
    int* p = &a[a[a[j]]];
    int* q = &a[a[a[a[a[*p]]]]];

    if(p == q){
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
