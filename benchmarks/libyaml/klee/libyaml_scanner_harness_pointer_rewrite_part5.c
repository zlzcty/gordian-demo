#include "/home/klee/klee_extra.h"
#include <klee/klee.h>
#include <yaml.h>
#include <string.h>

#define LIBYAML_KLEE_MAX_INPUT 256
#define LIBYAML_KLEE_MAX_TOKENS 512

/* Helper to create a YAML buffer with a fixed prefix and symbolic suffix */
static void make_yaml_input(unsigned char *buf, size_t total_size,
                            const char *prefix, size_t prefix_len) {
    memcpy(buf, (unsigned char*)prefix, prefix_len);
    if (total_size > prefix_len) {
        klee_make_symbolic(&buf[prefix_len], total_size - prefix_len, "yaml_tail");
    }
}

int main(void) {
    yaml_parser_t parser;
    yaml_token_t token;
    unsigned char data[LIBYAML_KLEE_MAX_INPUT];
    unsigned int count = 0;
    int ok;
    int klass = klee_range(1, 9, "case_selector");

    ok = yaml_parser_initialize(&parser);
    if (!ok) return 0;

    switch (klass) {
        case 1: /* C1: Directive with trailing comment and line break */
            make_yaml_input(data, sizeof(data), "%YAML 1.1 # comment\n", 20);
            yaml_parser_set_input_string(&parser, data, 20);
            break;
        case 2: /* C2: Directive with missing comment or line break */
            make_yaml_input(data, sizeof(data), "%YAML 1.1x", 9);
            yaml_parser_set_input_string(&parser, data, 9);
            break;
        case 3: /* C3: Directive with whitespace but no comment */
            make_yaml_input(data, sizeof(data), "%YAML 1.1  ", 11);
            yaml_parser_set_input_string(&parser, data, 11);
            break;
        case 4: /* C4: Empty directive name */
            make_yaml_input(data, sizeof(data), "% 1.1\n", 6);
            yaml_parser_set_input_string(&parser, data, 6);
            break;
        case 5: /* C5: Version directive with extremely long version number */
            make_yaml_input(data, sizeof(data), "%YAML 1234567890 1.0\n", 22);
            yaml_parser_set_input_string(&parser, data, 22);
            break;
        case 6: /* C6: Tag directive with missing whitespace after handle */
            make_yaml_input(data, sizeof(data), "%TAG !yaml!!tag:example.com,2000:app/\n", 39);
            yaml_parser_set_input_string(&parser, data, 39);
            break;
        case 7: /* C7: Tag token with canonical form and missing '>' */
            make_yaml_input(data, sizeof(data), "!<tag:example", 13);
            yaml_parser_set_input_string(&parser, data, 13);
            break;
        case 8: /* C8: Anchor with invalid trailing character */
            make_yaml_input(data, sizeof(data), "&anchor*", 8);
            yaml_parser_set_input_string(&parser, data, 8);
            break;
        default:
            klee_assume(0); /* unreachable */
    }

    while (count < LIBYAML_KLEE_MAX_TOKENS) {
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