#include "/home/klee/klee_extra.h"
#include <klee/klee.h>
#include <yaml.h>
#include <string.h>

#define LIBYAML_KLEE_MAX_INPUT 256
#define LIBYAML_KLEE_MAX_TOKENS 512

/* Helper to create a buffer with a fixed prefix and symbolic suffix */
static void make_mixed_buffer(unsigned char *buf, size_t total_size,
                              const char *prefix, size_t *used_len) {
    size_t prefix_len = strlen(prefix);
    memcpy(buf, (unsigned char*)prefix, prefix_len);
    
    /* Make the rest symbolic */
    if (prefix_len < total_size) {
        klee_make_symbolic(buf + prefix_len, total_size - prefix_len, "sym_suffix");
    }
    
    /* For cases where we want exactly prefix_len bytes */
    *used_len = prefix_len;
}

/* Helper for multi-byte UTF-8 character */
static void add_utf8_char(unsigned char *buf, size_t pos, unsigned char utf8_seq[4], int seq_len) {
    for (int i = 0; i < seq_len; i++) {
        buf[pos + i] = utf8_seq[i];
    }
}

int main(void) {
    yaml_parser_t parser;
    yaml_token_t token;
    unsigned char data[LIBYAML_KLEE_MAX_INPUT];
    unsigned int count = 0;
    int ok;
    size_t used_len = 0;
    
    int klass = klee_range(1, 9, "klass");
    
    ok = yaml_parser_initialize(&parser);
    if (!ok) {
        return 0;
    }
    
    switch (klass) {
        case 1: { /* Multi-byte UTF-8 character */
            /* "key: café" - 'é' is 0xC3 0xA9 in UTF-8 */
            const char *prefix = "key: caf";
            unsigned char utf8_e_acute[2] = {0xC3, 0xA9};
            memcpy(data, (unsigned char*)prefix, 8);
            add_utf8_char(data, 8, utf8_e_acute, 2);
            used_len = 10;
            break;
        }
        
        case 2: { /* CRLF line ending */
            const char *prefix = "key: value\r\n";
            memcpy(data, (unsigned char*)prefix, 12);
            used_len = 12;
            break;
        }
        
        case 3: { /* Single-byte line break (LF) */
            const char *prefix = "key: value\nnext: item";
            memcpy(data, (unsigned char*)prefix, 23);
            used_len = 23;
            break;
        }
        
        case 4: { /* Plain scalar ending with EOF */
            const char *prefix = "plain_scalar";
            memcpy(data, (unsigned char*)prefix, 12);
            used_len = 12;
            break;
        }
        
        case 5: { /* Directive line */
            const char *prefix = "%YAML 1.2\n";
            memcpy(data, (unsigned char*)prefix, 10);
            used_len = 10;
            break;
        }
        
        case 6: { /* Flow collection with line break */
            const char *prefix = "[ a,\n b ]";
            memcpy(data, (unsigned char*)prefix, 9);
            used_len = 9;
            break;
        }
        
        case 7: { /* Block scalar with mixed line breaks */
            const char *prefix = "|\n  line1\r\n  line2\n";
            memcpy(data, (unsigned char*)prefix, 19);
            used_len = 19;
            break;
        }
        
        case 8: { /* Comment with multi-byte UTF-8 */
            const char *prefix = "# comment with café\n";
            unsigned char utf8_e_acute[2] = {0xC3, 0xA9};
            memcpy(data, (unsigned char*)prefix, 13); /* "# comment with caf" */
            add_utf8_char(data, 13, utf8_e_acute, 2);
            data[15] = '\n';
            used_len = 16;
            break;
        }
        
        default:
            klee_assert(0 && "Invalid klass");
    }
    
    /* Make any remaining bytes symbolic for exploration */
    if (used_len < sizeof(data)) {
        klee_make_symbolic(data + used_len, sizeof(data) - used_len, "trailing_sym");
    }
    
    yaml_parser_set_input_string(&parser, data, used_len);
    
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
    return 0;
}