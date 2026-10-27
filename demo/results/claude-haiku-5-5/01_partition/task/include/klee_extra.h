// /home/klee/klee_extra.h
#pragma once
#include <klee/klee.h>

#define klee_choose(name, lo, hi) ({                 \
  int _x;                                            \
  klee_make_symbolic(&_x, sizeof(_x), (name));       \
  klee_assume((_x) >= (lo));                         \
  klee_assume((_x) <= (hi));                         \
  _x;                                                \
})

/* Shim so both names work */
#define klee_choose_int(name, lo, hi) klee_choose((name), (lo), (hi))
