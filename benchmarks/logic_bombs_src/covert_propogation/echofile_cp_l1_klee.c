#include <klee/klee.h>
/*
TOY:
*/
#include <string.h> 
#include "utils.h"

#include "a_tester.h"

// {"s":{"length": 4}}
int logic_bomb(char* s) {
    int symvar = s[0] - 48;
    int j;
    char file[] = "tmp.covpro";
    char cmd[256];
    sprintf(cmd, "echo %d > %s\n", symvar, file); 
    system(cmd);

    FILE *fp = stdin;
    fp = fopen(file, "r");
    fscanf(fp,"%d",&j);
    fclose(fp);
    remove(file);

    if(j == 7){
        return BOMB_ENDING;
    } else{
        return NORMAL_ENDING;
    }
}

int main(int argc, char** argv) {
char s[5];
klee_make_symbolic(&s, sizeof(s), "s");
klee_assume(s[4]=='\0');
return logic_bomb(s);
}
