#include "/home/klee/klee_extra.h"
#include <klee/klee.h>
#include <yaml.h>
#include <string.h>
#include <stdlib.h>

#define MAX_INPUT_SIZE 128
#define MAX_EVENTS 128

/* Helper to create a symbolic buffer with a concrete prefix */
static void make_buf_with_prefix(unsigned char *buf, size_t total_size,
                                 const char *prefix, size_t prefix_len) {
    if (prefix_len > 0) {
        memcpy(buf, prefix, prefix_len);
    }
    if (total_size > prefix_len) {
        klee_make_symbolic(buf + prefix_len, total_size - prefix_len, "sym_part");
    }
}

int main(void) {
    yaml_parser_t parser;
    yaml_event_t event;
    unsigned char data[MAX_INPUT_SIZE];
    unsigned int count = 0;
    int ok;
    int klass;

    klee_make_symbolic(&klass, sizeof(klass), "klass");
    klass = klee_range(1, 9, "klass_range");

    switch (klass) {
        case 1: /* C1: Flow mapping with missing separator */
            make_buf_with_prefix(data, sizeof(data), "{a: ", 4);
            data[sizeof(data)-1] = '}';
            break;
            
        case 2: /* C2: Flow mapping with explicit empty value */
            make_buf_with_prefix(data, sizeof(data), "{a: , b: 1}", 11);
            break;
            
        case 3: /* C3: Duplicate YAML version directive */
            make_buf_with_prefix(data, sizeof(data), "%YAML 1.2\n%YAML 1.2\n---\n", 24);
            break;
            
        case 4: /* C4: Incompatible YAML version directive */
            make_buf_with_prefix(data, sizeof(data), "%YAML 1.3\n---\n", 14);
            break;
            
        case 5: /* C5: Memory allocation failure during empty scalar creation */
            /* Trigger empty scalar creation through empty flow mapping */
            make_buf_with_prefix(data, sizeof(data), "{a:}", 4);
            break;
            
        case 6: /* C6: Memory allocation failure during tag directive duplication */
            make_buf_with_prefix(data, sizeof(data), "%TAG ! !foo:\n", 13);
            break;
            
        case 7: /* C7: Duplicate %TAG directive without allow_duplicates flag */
            make_buf_with_prefix(data, sizeof(data), "%TAG ! !foo:\n%TAG ! !foo:\n---\n", 28);
            break;
            
        case 8: /* C8: Flow mapping key with immediate terminator */
            make_buf_with_prefix(data, sizeof(data), "{a}", 3);
            break;
            
        default:
            /* Fallback: simple YAML */
            make_buf_with_prefix(data, sizeof(data), "---\n", 4);
            break;
    }

    ok = yaml_parser_initialize(&parser);
    if (!ok) {
        return 0;
    }

    yaml_parser_set_input_string(&parser, data, sizeof(data));

    while (count < MAX_EVENTS) {
        ok = yaml_parser_parse(&parser, &event);
        if (!ok) {
            break;
        }

        if (event.type == YAML_STREAM_END_EVENT) {
            yaml_event_delete(&event);
            break;
        }

        yaml_event_delete(&event);
        ++count;
    }

    yaml_parser_delete(&parser);
    return 0;
}