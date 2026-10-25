#include <klee/klee.h>
extern int logic_bomb(char* s);
/* Assumption: float arithmetic in logic_bomb is only fed concrete s[0] (chosen per case);
   the remaining bytes stay symbolic. Bomb needs s[0]-48 == 7, i.e. s[0]=='7' (7/70.0 -> float 0.1f != 0.1 double). */

/* Family 1: the trigger digit, with various symbolic tails. */
int main(int argc, char **argv) {
  char s[5];
  int klass = klee_range(0, 4, "klass");
  klee_make_symbolic(s, sizeof s, "s");
  s[4] = 0;
  switch (klass) {
  case 0: s[0] = '7'; break;
  case 1: s[0] = '7'; klee_assume(s[1] == 0); break;
  case 2: s[0] = '7'; klee_assume(s[1] >= '0' && s[1] <= '9'); klee_assume(s[2] == 0); break;
  default: s[0] = '7'; klee_assume(s[1] != 0); klee_assume(s[2] != 0); klee_assume(s[3] != 0); break;
  }
  return logic_bomb(s);
}
