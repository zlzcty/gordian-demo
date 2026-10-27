#pragma once
#include <stddef.h>
#include <stdint.h>
void klee_make_symbolic(void *addr, size_t nbytes, const char *name);
void klee_assume(uintptr_t condition);
void klee_assert(uintptr_t condition);
uintptr_t klee_range(uintptr_t start, uintptr_t end, const char *name);
void klee_silent_exit(int status);
