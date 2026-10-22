#include <klee/klee.h>
#include "jv.h"

int main(int argc, char **argv) {
     char input[255];

    klee_make_symbolic(input, sizeof(input), "json_input");
    input[254] = '\0';   // ensure termination

    jv v = jv_parse(input);

    if (jv_is_valid(v)) {
        jv_free(v);
    }

    return 0;
}