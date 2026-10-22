#include "/home/klee/klee_extra.h"
#include <klee/klee.h>
#include <yaml.h>

#define LIBYAML_KLEE_MAX_INPUT 256
#define LIBYAML_KLEE_MAX_TOKENS 512

static void build_yaml_with_symbolic_suffix(unsigned char *buf, size_t fixed_len, size_t total_len) {
    if (fixed_len < total_len) {
        klee_make_symbolic(buf + fixed_len, total_len - fixed_len, "yaml_suffix");
    }
}

static void scan_stream(unsigned char *data, size_t len) {
    yaml_parser_t parser;
    yaml_token_t token;
    unsigned int count = 0;
    int ok;

    ok = yaml_parser_initialize(&parser);
    if (!ok) return;

    yaml_parser_set_input_string(&parser, data, len);
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
}

int main(void) {
    unsigned char data[LIBYAML_KLEE_MAX_INPUT];
    int klass = klee_range(1, 9, "klass");

    switch (klass) {
        case 1: { // C1: Non-empty YAML stream with simple key at head
            // "key: value" with symbolic value
            size_t fixed = 4; // "key"
            memcpy(data, "key:", fixed);
            build_yaml_with_symbolic_suffix(data, fixed, 32);
            scan_stream(data, 32);
            break;
        }
        
        case 2: { // C2: YAML stream with explicit document start/end markers
            // "---\n...\n"
            size_t fixed = 8;
            memcpy(data, "---\n...\n", fixed);
            scan_stream(data, fixed);
            break;
        }
        
        case 3: { // C3: Flow collection with nested structure
            // "[item, {key: value}]" with symbolic items
            size_t fixed = 1; // "["
            data[0] = '[';
            build_yaml_with_symbolic_suffix(data, fixed, 64);
            // Ensure closing bracket exists for valid parsing
            if (64 > 1) data[63] = ']';
            scan_stream(data, 64);
            break;
        }
        
        case 4: { // C4: Block scalar with line breaks
            // "| \n" prefix for literal block scalar
            size_t fixed = 3;
            memcpy(data, "| \n", fixed);
            build_yaml_with_symbolic_suffix(data, fixed, 128);
            scan_stream(data, 128);
            break;
        }
        
        case 5: { // C5: Directive and tag handling with malformed URI escapes
            // "%TAG ! !<" prefix with symbolic malformed URI
            size_t fixed = 8;
            memcpy(data, "%TAG ! !<", fixed);
            build_yaml_with_symbolic_suffix(data, fixed, 48);
            scan_stream(data, 48);
            break;
        }
        
        case 6: { // C6: Anchor and alias reuse across documents
            // "---\n&anchor value\n...\n---\n*anchor\n...\n"
            size_t fixed = 32;
            memcpy(data, "---\n&anchor value\n...\n---\n*anchor\n...\n", fixed);
            scan_stream(data, fixed);
            break;
        }
        
        case 7: { // C7: Plain scalar with trailing colon not followed by whitespace
            // "key:value" (no space after colon)
            size_t fixed = 9;
            memcpy(data, "key:value", fixed);
            scan_stream(data, fixed);
            break;
        }
        
        case 8: { // C8: Empty or whitespace-only stream
            // All whitespace
            size_t fixed = 16;
            memset(data, ' ', fixed);
            scan_stream(data, fixed);
            break;
        }
    }
    
    return 0;
}