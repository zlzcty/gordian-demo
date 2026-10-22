#include "/home/klee/klee_extra.h"
#include <klee/klee.h>
#include <yaml.h>
#include <string.h>

#define LIBYAML_KLEE_MAX_INPUT 128
#define LIBYAML_KLEE_MAX_EVENTS 128

static void build_yaml_input(unsigned char *data, int klass) {
    int symbolic_len;
    klee_make_symbolic(&symbolic_len, sizeof(symbolic_len), "symbolic_len");
    klee_assume(symbolic_len >= 0 && symbolic_len < LIBYAML_KLEE_MAX_INPUT - 32);
    
    // Create symbolic payload for content
    unsigned char payload[LIBYAML_KLEE_MAX_INPUT];
    klee_make_symbolic(payload, sizeof(payload), "payload");
    
    memset(data, 0, LIBYAML_KLEE_MAX_INPUT);
    
    switch(klass) {
        case 1: // Empty block sequence entry
            strcpy((char*)data, "---\n- \n- ");
            memcpy(data + 7, payload, symbolic_len);
            data[7 + symbolic_len] = '\n';
            break;
            
        case 2: // Block mapping with missing value
            strcpy((char*)data, "---\n? key\n? ");
            memcpy(data + 11, payload, symbolic_len);
            data[11 + symbolic_len] = '\n';
            break;
            
        case 3: // Flow sequence with implicit empty mapping
            strcpy((char*)data, "---\n[ ? ");
            memcpy(data + 7, payload, symbolic_len);
            strcat((char*)data, " ]");
            break;
            
        case 4: // Flow mapping with key but no value
            strcpy((char*)data, "---\n{ key: ");
            memcpy(data + 10, payload, symbolic_len);
            strcat((char*)data, " , other: value }");
            break;
            
        case 5: // Indentless sequence with trailing entry
            strcpy((char*)data, "---\n- item\n- ");
            memcpy(data + 12, payload, symbolic_len);
            data[12 + symbolic_len] = '\n';
            break;
            
        case 6: // Block sequence termination error
            strcpy((char*)data, "---\n- item\ninvalid");
            memcpy(data + 13, payload, symbolic_len);
            data[13 + symbolic_len] = '\n';
            break;
            
        case 7: // Flow sequence entry mapping with missing value
            strcpy((char*)data, "---\n[ ? key : ");
            memcpy(data + 13, payload, symbolic_len);
            strcat((char*)data, " , other ]");
            break;
            
        default:
            // Fallback: simple document
            strcpy((char*)data, "---\n");
            memcpy(data + 4, payload, symbolic_len);
            data[4 + symbolic_len] = '\n';
            break;
    }
}

int main(void) {
    yaml_parser_t parser;
    yaml_event_t event;
    unsigned char data[LIBYAML_KLEE_MAX_INPUT];
    unsigned int count = 0;
    int ok;
    
    // Choose which semantic case to explore
    int klass;
    klee_make_symbolic(&klass, sizeof(klass), "klass");
    klee_assume(klass >= 1 && klass <= 7);
    
    // Build YAML input according to the chosen case
    build_yaml_input(data, klass);
    
    ok = yaml_parser_initialize(&parser);
    if (!ok) {
        return 0;
    }
    
    yaml_parser_set_input_string(&parser, data, strlen((char*)data));
    
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