#include <klee/klee.h>
#include <pthread.h>
#include <time.h>
#include <unistd.h>
#include "a_tester.h"

void* trigger(void* i){
    sleep(5);
    ++ *((int*) i);
}

// {"s":{"length": 4}}
int logic_bomb(char* s) {
    int symvar = s[0] - 48;
    int i = symvar + 1;
    pthread_t tid;
    int rc = pthread_create(&tid, NULL, trigger, (void *) &symvar); 
    while (symvar != i){
	sleep(1);
        symvar ++;
        i ++;
    }
    rc = pthread_join(tid, NULL); 
    if(symvar == 13)
        return  BOMB_ENDING;
    return  NORMAL_ENDING;
}

int main(int argc, char** argv) {
char s[5];
klee_make_symbolic(&s, sizeof(s), "s");
klee_assume(s[4]=='\0');
return logic_bomb(s);
}
