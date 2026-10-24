#include <klee/klee.h>
#include <stdlib.h>
#include "a_tester.h"

extern int logic_bomb(char* s);

int main() {
  int klass = klee_range(0, 3, "klass");
  char s[5];

  switch (klass) {
    case 0:
      klee_make_symbolic(&s, sizeof(s), "s");
      klee_assume(s[4] == '\0');
      klee_assume(s[0] == '1');
      break;
    case 1:
      klee_make_symbolic(&s, sizeof(s), "s");
      klee_assume(s[4] == '\0');
      klee_assume(s[0] == '2');
      break;
    case 2:
      klee_make_symbolic(&s, sizeof(s), "s");
      klee_assume(s[4] == '\0');
      klee_assume(s[0] == '3');
      break;
  }

  return logic_bomb(s);
}
