#include "/home/klee/klee_extra.h"
#include <klee/klee.h>
#include <yaml.h>
#include <string.h>

#define LIBYAML_KLEE_MAX_INPUT 256
#define LIBYAML_KLEE_MAX_TOKENS 512

static void test_case(const unsigned char *data, size_t length) {
    yaml_parser_t parser;
    yaml_token_t token;
    unsigned int count = 0;
    int ok;

    ok = yaml_parser_initialize(&parser);
    if (!ok) {
        return;
    }

    yaml_parser_set_input_string(&parser, data, length);
    while (count < LIBYAML_KLEE_MAX_TOKENS) {
        ok = yaml_parser_scan(&parser, &token);
        if (!ok) {
            break;
        }

        if (token.type == YAML_STREAM_END_TOKEN) {
            yaml_token_delete(&token);
            break;
        }

        yaml_token_delete(&token);
        ++count;
    }

    yaml_parser_delete(&parser);
}

int main(void) {
    unsigned char data[LIBYAML_KLEE_MAX_INPUT];
    int klass = klee_range(1, 9, "klass");
    
    switch (klass) {
        case 1: { // Block scalar with '|' or '>'
            // Minimal: "---\n|-\n  x\n"
            memcpy(data, "---\n|-\n  ", 9);
            klee_make_symbolic(data + 9, 8, "block_scalar_content");
            data[17] = '\n';
            test_case(data, 18);
            break;
        }
        
        case 2: { // Flow scalar with quotes
            // Minimal: "---\n\"x\"\n"
            memcpy(data, "---\n\"", 5);
            klee_make_symbolic(data + 5, 8, "quoted_content");
            data[13] = '\"';
            data[14] = '\n';
            test_case(data, 15);
            break;
        }
        
        case 3: { // Plain scalar starting with special chars in block context
            // Minimal: "---\n-?x\n"
            memcpy(data, "---\n-?", 6);
            klee_make_symbolic(data + 6, 8, "plain_scalar_tail");
            data[14] = '\n';
            test_case(data, 15);
            break;
        }
        
        case 4: { // Invalid token start character
            // Minimal: "---\n#x\n"
            memcpy(data, "---\n#", 5);
            klee_make_symbolic(data + 5, 8, "comment_content");
            data[13] = '\n';
            test_case(data, 14);
            break;
        }
        
        case 5: { // Simple key expiration across lines
            // Key starts line 1, colon on line 2 with >1024 chars between
            // We'll simulate with moderate distance
            memcpy(data, "---\nkey", 7);
            // Add many spaces
            for (int i = 7; i < 64; i++) data[i] = ' ';
            memcpy(data + 64, "\n:", 2);
            klee_make_symbolic(data + 66, 8, "value_part");
            data[74] = '\n';
            test_case(data, 75);
            break;
        }
        
        case 6: { // Required simple key missing in flow context
            // Minimal: "---\n{key\n"
            memcpy(data, "---\n{key", 8);
            klee_make_symbolic(data + 8, 8, "flow_rest");
            data[16] = '\n';
            test_case(data, 17);
            break;
        }
        
        case 7: { // Indentation increase with token insertion
            // Minimal: "---\n- \n  - x\n"
            memcpy(data, "---\n- \n  - ", 11);
            klee_make_symbolic(data + 11, 8, "indented_content");
            data[19] = '\n';
            test_case(data, 20);
            break;
        }
        
        case 8: { // Flow level operations at maximum depth
            // Deep nested flow: "---\n[[[[[[[[[[[[[[[[[[[["
            memcpy(data, "---\n", 4);
            // Create 20 levels of nesting (well below INT_MAX but deep enough)
            for (int i = 0; i < 20; i++) {
                data[4 + i] = '[';
            }
            klee_make_symbolic(data + 24, 8, "deep_flow_content");
            data[32] = '\n';
            test_case(data, 33);
            break;
        }
    }
    
    return 0;
}