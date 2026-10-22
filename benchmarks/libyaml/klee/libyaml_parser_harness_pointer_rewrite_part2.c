#include "/home/klee/klee_extra.h"
#include <klee/klee.h>
#include <yaml.h>
#include <string.h>

#define LIBYAML_KLEE_MAX_INPUT 128
#define LIBYAML_KLEE_MAX_EVENTS 128

// Helper to create symbolic strings
static void make_symbolic_string(char *buf, size_t size, const char *name) {
    for (size_t i = 0; i < size - 1; i++) {
        klee_make_symbolic(&buf[i], 1, name);
        // Restrict to printable ASCII for tag handles/scalars
        klee_assume(buf[i] >= 32 && buf[i] <= 126);
    }
    buf[size - 1] = '\0';
}

int main(void) {
    yaml_parser_t parser;
    yaml_event_t event;
    unsigned char data[LIBYAML_KLEE_MAX_INPUT];
    unsigned int count = 0;
    int ok;

    int klass = klee_range(1, 9, "klass");
    
    // Initialize with zeros
    memset(data, 0, sizeof(data));
    
    switch (klass) {
        case 1: // C1: Empty YAML Stream with Document End
            strcpy((char*)data, "...");
            break;
            
        case 2: // C2: Document with Directives but No Content
            strcpy((char*)data, "%YAML 1.2\n---\n...");
            break;
            
        case 3: // C3: Anchor Followed by Tag in Flow Node
            strcpy((char*)data, "[ &anchor !!str ");
            // Symbolic scalar content
            make_symbolic_string((char*)data + strlen((char*)data), 
                                sizeof(data) - strlen((char*)data), "flow_scalar");
            strcat((char*)data, " ]");
            break;
            
        case 4: // C4: Tag Followed by Anchor in Block Node
            strcpy((char*)data, "!!int &ref ");
            // Symbolic scalar content
            make_symbolic_string((char*)data + strlen((char*)data),
                                sizeof(data) - strlen((char*)data), "block_scalar");
            break;
            
        case 5: // C5: Undefined Tag Handle in Node Properties
            strcpy((char*)data, "!my! ");
            // Symbolic scalar content
            make_symbolic_string((char*)data + strlen((char*)data),
                                sizeof(data) - strlen((char*)data), "tag_scalar");
            break;
            
        case 6: // C6: Indentless Sequence Entry with Anchor/Tag
            strcpy((char*)data, "- &anchor !!str ");
            // Symbolic scalar content
            make_symbolic_string((char*)data + strlen((char*)data),
                                sizeof(data) - strlen((char*)data), "seq_scalar");
            break;
            
        case 7: // C7: Plain Scalar with Null Tag Implicitly Resolved
            strcpy((char*)data, "value");
            break;
            
        case 8: // C8: Node with Only Anchor and Tag but No Content
            strcpy((char*)data, "&anchor !!str");
            break;
    }

    ok = yaml_parser_initialize(&parser);
    if (!ok) {
        return 0;
    }

    yaml_parser_set_input_string(&parser, data, strlen((char*)data));
    // Note: yaml_set_max_nest_level doesn't exist in libyaml API
    // This appears to be a custom function not in standard libyaml
    // We'll comment it out and rely on default behavior
    // yaml_set_max_nest_level(32);

    while (count < LIBYAML_KLEE_MAX_EVENTS) {
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