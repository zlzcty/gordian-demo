#include <klee/klee.h>
#include <unistd.h>
#include "utils.h"
#include "a_tester.h"

// {"s":{"length": 2}}
int logic_bomb(char* s) {
    int pid, fd[2];
    pipe(fd);
    if ((pid = fork()) == -1)
        return NORMAL_ENDING;
    if (pid == 0) {
        close(fd[0]);
        write(fd[1], s, sizeof(s));
        wait(NULL);
	exit(0);
    }
    else {
        char content[8];
        close(fd[1]);
        read(fd[0], content, 8);
        if (strcmp(content, "7") == 0) {
            return BOMB_ENDING;
        }
        return NORMAL_ENDING; 
    }
}

int main(int argc, char** argv) {
char s[3];
klee_make_symbolic(&s, sizeof(s), "s");
klee_assume(s[2]=='\0');
return logic_bomb(s);
}
