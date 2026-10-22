#include <klee/klee.h>
#include <stddef.h>
#include <stdlib.h>

#define LIBYAML_KLEE_WEAK __attribute__((weak))

static size_t libyaml_klee_strlen_impl(const char *s)
{
    size_t len = 0;

    while (s[len] != '\0') {
        ++len;
    }

    return len;
}

LIBYAML_KLEE_WEAK int strcmp(const char *lhs, const char *rhs)
{
    while (*lhs != '\0' && *lhs == *rhs) {
        ++lhs;
        ++rhs;
    }

    return (unsigned char)*lhs - (unsigned char)*rhs;
}

LIBYAML_KLEE_WEAK int strncmp(const char *lhs, const char *rhs, size_t n)
{
    size_t i;

    for (i = 0; i < n; ++i) {
        unsigned char a = (unsigned char)lhs[i];
        unsigned char b = (unsigned char)rhs[i];

        if (a != b) {
            return a - b;
        }

        if (a == '\0') {
            return 0;
        }
    }

    return 0;
}

LIBYAML_KLEE_WEAK size_t strlen(const char *s)
{
    return libyaml_klee_strlen_impl(s);
}

LIBYAML_KLEE_WEAK int memcmp(const void *lhs, const void *rhs, size_t n)
{
    const unsigned char *a = (const unsigned char *)lhs;
    const unsigned char *b = (const unsigned char *)rhs;
    size_t i;

    for (i = 0; i < n; ++i) {
        if (a[i] != b[i]) {
            return a[i] - b[i];
        }
    }

    return 0;
}

LIBYAML_KLEE_WEAK char *strdup(const char *s)
{
    size_t len = libyaml_klee_strlen_impl(s);
    char *copy = (char *)malloc(len + 1);
    size_t i;

    if (copy == NULL) {
        return NULL;
    }

    for (i = 0; i <= len; ++i) {
        copy[i] = s[i];
    }

    return copy;
}

LIBYAML_KLEE_WEAK void *memcpy(void *dst, const void *src, size_t n)
{
    unsigned char *out = (unsigned char *)dst;
    const unsigned char *in = (const unsigned char *)src;
    size_t i;

    for (i = 0; i < n; ++i) {
        out[i] = in[i];
    }

    return dst;
}

LIBYAML_KLEE_WEAK void *memmove(void *dst, const void *src, size_t n)
{
    unsigned char *out = (unsigned char *)dst;
    const unsigned char *in = (const unsigned char *)src;
    size_t i;

    if (out == in || n == 0) {
        return dst;
    }

    if (out < in) {
        for (i = 0; i < n; ++i) {
            out[i] = in[i];
        }
    } else {
        for (i = n; i > 0; --i) {
            out[i - 1] = in[i - 1];
        }
    }

    return dst;
}

LIBYAML_KLEE_WEAK void *memset(void *dst, int value, size_t n)
{
    unsigned char *out = (unsigned char *)dst;
    unsigned char byte = (unsigned char)value;
    size_t i;

    for (i = 0; i < n; ++i) {
        out[i] = byte;
    }

    return dst;
}
