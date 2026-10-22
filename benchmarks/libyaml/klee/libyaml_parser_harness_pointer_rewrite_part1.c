#include "/home/klee/klee_extra.h"
#include <klee/klee.h>
#include <yaml.h>

#define LIBYAML_KLEE_MAX_INPUT 128
#define LIBYAML_KLEE_MAX_EVENTS 128

static void setup_parser(yaml_parser_t *parser, unsigned char *data, size_t size) {
    yaml_parser_initialize(parser);
    yaml_parser_set_input_string(parser, data, size);
}

static void parse_events(yaml_parser_t *parser) {
    yaml_event_t event;
    unsigned int count = 0;
    
    while (count < LIBYAML_KLEE_MAX_EVENTS) {
        int ok = yaml_parser_parse(parser, &event);
        if (!ok) break;
        
        if (event.type == YAML_STREAM_END_EVENT) {
            yaml_event_delete(&event);
            break;
        }
        yaml_event_delete(&event);
        ++count;
    }
}

int main(void) {
    unsigned char data[LIBYAML_KLEE_MAX_INPUT];
    yaml_parser_t parser;
    int klass = klee_range(1, 9, "case_selector");
    
    switch (klass) {
        case 1: { // C1: Empty YAML Stream
            // Stream start + immediate stream end
            data[0] = 0; // Empty input triggers implicit stream end
            klee_make_symbolic(data, 1, "empty_stream");
            setup_parser(&parser, data, 1);
            parse_events(&parser);
            break;
        }
        
        case 2: { // C2: Explicit Document with Directives
            // %YAML 1.2\n---\n... (explicit document with directives)
            const char *skeleton = "%YAML 1.2\n---\n...";
            size_t len = strlen(skeleton);
            memcpy(data, skeleton, len);
            // Make version number symbolic for exploration
            if (len >= 8) klee_make_symbolic(&data[6], 3, "version_part");
            setup_parser(&parser, data, len);
            parse_events(&parser);
            break;
        }
        
        case 3: { // C3: Malformed Document Start
            // %YAML 1.2 (missing ---)
            const char *skeleton = "%YAML 1.2";
            size_t len = strlen(skeleton);
            memcpy(data, skeleton, len);
            klee_make_symbolic(&data[6], 3, "version_part");
            setup_parser(&parser, data, len);
            parse_events(&parser);
            break;
        }
        
        case 4: { // C4: Nested Block Sequence at Maximum Depth
            // Create deeply nested sequence: "- - - ..."
            // Use bounded depth (e.g., 10) to avoid infinite loops
            int depth = 10;
            size_t pos = 0;
            for (int i = 0; i < depth; i++) {
                data[pos++] = '-';
                data[pos++] = ' ';
            }
            data[pos++] = '\n';
            klee_make_symbolic(&data[depth*2], 1, "nested_content");
            setup_parser(&parser, data, pos);
            parse_events(&parser);
            break;
        }
        
        case 5: { // C5: Flow Mapping with Empty Key-Value Pair
            // { : value} or {:}
            const char *skeleton = "{ : ";
            size_t base_len = strlen(skeleton);
            memcpy(data, skeleton, base_len);
            // Symbolic value and closing brace
            klee_make_symbolic(&data[base_len], 8, "flow_value");
            data[base_len + 8] = '}';
            setup_parser(&parser, data, base_len + 9);
            parse_events(&parser);
            break;
        }
        
        case 6: { // C6: Document with Extra End Markers
            // ... ... --- (multiple ends before start)
            const char *skeleton = "...\n...\n---";
            size_t len = strlen(skeleton);
            memcpy(data, skeleton, len);
            setup_parser(&parser, data, len);
            parse_events(&parser);
            break;
        }
        
        case 7: { // C7: Parser Error State Before Event Generation
            // Invalid anchor: &@ (invalid anchor name)
            const char *skeleton = "&@ invalid";
            size_t len = strlen(skeleton);
            memcpy(data, skeleton, len);
            // Make invalid character symbolic
            klee_make_symbolic(&data[1], 1, "invalid_anchor_char");
            setup_parser(&parser, data, len);
            parse_events(&parser);
            break;
        }
        
        case 8: { // C8: Invalid Parser State Transition
            // Malformed sequence: "-" without newline or content
            // followed by unexpected token
            const char *skeleton = "-";
            size_t len = strlen(skeleton);
            memcpy(data, skeleton, len);
            // Add symbolic byte that might cause state corruption
            klee_make_symbolic(&data[len], 1, "corrupting_byte");
            setup_parser(&parser, data, len + 1);
            parse_events(&parser);
            break;
        }
    }
    
    yaml_parser_delete(&parser);
    return 0;
}