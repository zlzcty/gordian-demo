#include "/home/klee/klee_extra.h"
#include <klee/klee.h>
#include <yaml.h>
#include <string.h>

#define MAX_INPUT 256
#define MAX_TOKENS 512

/* Helper to create a YAML prefix and leave the rest symbolic */
static void make_yaml_input(unsigned char *buf, int total_size,
                            const char *prefix, int *used_len) {
    int prefix_len = strlen(prefix);
    memcpy(buf, (unsigned char*)prefix, prefix_len);
    *used_len = prefix_len;
    if (prefix_len < total_size) {
        klee_make_symbolic(buf + prefix_len, total_size - prefix_len, "yaml_suffix");
    }
}

int main(void) {
    yaml_parser_t parser;
    yaml_token_t token;
    unsigned char data[MAX_INPUT];
    unsigned int count = 0;
    int ok;
    int klass;

    klee_make_symbolic(&klass, sizeof(klass), "klass");
    klee_assume(klass >= 1 && klass <= 17);

    ok = yaml_parser_initialize(&parser);
    if (!ok) return 0;

    int used_len = 0;

    switch (klass) {
        case 1:  /* Flow context with simple keys and flow entry */
            make_yaml_input(data, MAX_INPUT, "[a,", &used_len);
            break;
        case 2:  /* Block context, simple key disallowed for block entry */
            make_yaml_input(data, MAX_INPUT, "key:\n -", &used_len);
            break;
        case 3:  /* Block context, simple key allowed for block entry */
            make_yaml_input(data, MAX_INPUT, "-\n -", &used_len);
            break;
        case 4:  /* Block context mapping key, simple key disallowed */
            make_yaml_input(data, MAX_INPUT, "key: value\n?", &used_len);
            break;
        case 5:  /* Block context mapping key, simple key allowed */
            make_yaml_input(data, MAX_INPUT, "?\n", &used_len);
            break;
        case 6:  /* Flow context mapping value after complex key */
            make_yaml_input(data, MAX_INPUT, "{? key:", &used_len);
            break;
        case 7:  /* Block context mapping value, simple key disallowed */
            make_yaml_input(data, MAX_INPUT, "key:\n:", &used_len);
            break;
        case 8:  /* Block context mapping value, simple key allowed */
            make_yaml_input(data, MAX_INPUT, ":\n", &used_len);
            break;
        case 9:  /* Simple key resolution for mapping value */
            make_yaml_input(data, MAX_INPUT, "key:", &used_len);
            break;
        case 10: /* Anchor or alias as potential simple key */
            make_yaml_input(data, MAX_INPUT, "&anchor ", &used_len);
            break;
        case 11: /* Tag as potential simple key */
            make_yaml_input(data, MAX_INPUT, "!tag ", &used_len);
            break;
        case 12: /* Block scalar resetting simple keys */
            make_yaml_input(data, MAX_INPUT, "|\n", &used_len);
            break;
        case 13: /* Flow scalar as potential simple key */
            make_yaml_input(data, MAX_INPUT, "\"", &used_len);
            break;
        case 14: /* Plain scalar as potential simple key */
            make_yaml_input(data, MAX_INPUT, "scalar\n", &used_len);
            break;
        case 15: /* Scanner whitespace with tabs in flow context */
            make_yaml_input(data, MAX_INPUT, "[\t", &used_len);
            break;
        case 16: /* Newline resetting simple_key_allowed in block context */
            make_yaml_input(data, MAX_INPUT, "key:\n  value\n", &used_len);
            break;
        case 17: /* Unknown directive error */
            make_yaml_input(data, MAX_INPUT, "%FOO\n", &used_len);
            break;
        default:
            klee_assume(0);
    }

    yaml_parser_set_input_string(&parser, data, used_len);
    while (count < MAX_TOKENS) {
        ok = yaml_parser_scan(&parser, &token);
        if (!ok) break;

        if (token.type == YAML_STREAM_END_TOKEN) {
            yaml_token_delete(&token);
            break;
        }
        yaml_token_delete(&token);
        ++count;
    }

    yaml_parser_delete(&parser);
    return 0;
}