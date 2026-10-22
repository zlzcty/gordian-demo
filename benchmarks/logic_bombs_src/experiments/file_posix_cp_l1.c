#include <string.h>

#include "utils.h"
#include "a_tester.h"
#include "../../assume.h"

// {"s": {"length": 4}}
int logic_bomb(char* s) {
    assume_NL_start;
    int symvar = s[0] - 48;
    int j;
    char file[] = "tmp.covpro";
    int fd = open(file, O_CREAT | O_WRONLY | O_TRUNC, S_IRUSR | S_IWUSR);
    if(fd < 0)
    {
        exit(-1);             
    }
    write(fd, &symvar, sizeof symvar);
    close(fd);
    fd = open(file, O_RDONLY);
    read(fd, &j, sizeof j);
    close(fd);
    assume_NL_stop;
    if(j == 7){
        return 1;
    } else{
        return 0;
    }
}
