#include <klee/klee.h>
/*
TOY:
Result:
Triton: Pin is out of memory: MmapChecked

*/
#include <string.h> 
#include "utils.h"
#include "a_tester.h"

// {"s":{"length": 4}}
int logic_bomb(char* s) {
    int symvar = s[0] - 48;
    int j;
    char file[] = "tmp.covpro";
    FILE *fp = fopen(file, "ab+");
    if(fp == NULL)
    {
        //printf("Error!");   
        exit(1);             
    }
    fprintf(fp,"%d",symvar);
    fclose(fp);

    fp = fopen("tmp.covpro", "r");
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
