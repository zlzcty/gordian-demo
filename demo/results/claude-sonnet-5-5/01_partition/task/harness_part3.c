#include <klee/klee.h>
extern int logic_bomb(char* s);
/* Assumption: float arithmetic in logic_bomb is only fed concrete s[0] (chosen per case);
   the remaining bytes stay symbolic. Bomb needs s[0]-48 == 7, i.e. s[0]=='7' (7/70.0 -> float 0.1f != 0.1 double). */

/* Family 3: remaining digits (concrete choice via klee_range) and non-digit leading characters. */
int main(int argc, char **argv) {
  char s[5];
  int klass = klee_range(0, 4, "klass");
  int d = klee_range(0, 10, "d");
  klee_make_symbolic(s, sizeof s, "s");
  s[4] = 0;
  switch (klass) {
  case 0: s[0] = '0' + d; break;                      /* every digit, incl. 7 */
  case 1: s[0] = 0; break;                            /* empty string */
  case 2: s[0] = 'a' + d; break;                      /* letters */
  default: s[0] = ' ' + d; break;                     /* punctuation / space */
  }
  return logic_bomb(s);
}
