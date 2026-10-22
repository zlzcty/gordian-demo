/*
TOY:
Result:
Triton: Pin is out of memory: MmapChecked

*/
#include <string.h> 
#include "utils.h"
#include "a_tester.h"
#include "../../assume.h"

// {"s":{"length": 4}}
int logic_bomb(char* s) {
    assume_NL_start;
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
    assume_NL_stop;
    if(j == 7){
        return BOMB_ENDING;
    } else{
        return NORMAL_ENDING;
    }
}
