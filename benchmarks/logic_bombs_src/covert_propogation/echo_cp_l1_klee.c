#include <klee/klee.h>
#include <string.h> 
#include "utils.h"

#include "a_tester.h"

char* shell(const char* cmd)
{
    char* rs = "";
    FILE *f;
    f = popen(cmd, "r");
    char buf[1024];
    memset(buf,'\0',sizeof(buf));
    while(fgets(buf,1024-1,f)!=NULL)
    { 
       rs = buf;
    }

    pclose(f);
    return rs;
}

// {"s":{"length": 4}}
int logic_bomb(char* s) {
    int symvar = s[0] - 48;
    char cmd[256];
    sprintf(cmd, "echo %d\n", symvar); 
    char* rs = shell(cmd);

   if(atoi(rs) == 7)
    return BOMB_ENDING;
   else
    return NORMAL_ENDING;
}

int main(int argc, char** argv) {
char s[5];
klee_make_symbolic(&s, sizeof(s), "s");
klee_assume(s[4]=='\0');
return logic_bomb(s);
}
