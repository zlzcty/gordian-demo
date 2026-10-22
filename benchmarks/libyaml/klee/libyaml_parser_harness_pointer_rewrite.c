#include "/home/klee/klee_extra.h"
#include <klee/klee.h>
#include <yaml.h>
#include <string.h>

#define LIBYAML_KLEE_MAX_INPUT 256
#define LIBYAML_KLEE_MAX_EVENTS 512

static void append_str(unsigned char *buf, size_t *len, size_t cap, const char *s) {
    size_t n = strlen(s);
    if (*len + n < cap) {
        memcpy(buf + *len, s, n);
        *len += n;
    }
}

static void append_bytes(unsigned char *buf, size_t *len, size_t cap, const unsigned char *src, size_t n) {
    if (*len + n < cap) {
        memcpy(buf + *len, src, n);
        *len += n;
    }
}

static void make_ascii_word(unsigned char *dst, const unsigned char *src, size_t n) {
    for (size_t i = 0; i < n; i++) {
        unsigned v = src[i] % 36;
        dst[i] = (unsigned char)((v < 26) ? ('a' + v) : ('0' + (v - 26)));
    }
}

int main(int argc, char **argv) {
    yaml_parser_t parser;
    yaml_event_t event;
    unsigned char data[LIBYAML_KLEE_MAX_INPUT];
    unsigned int count = 0;
    int ok;
    size_t len = 0;
    
    unsigned char klass;
    klee_make_symbolic(&klass, sizeof(klass), "klass");
    klass = klass % 8;
    
    unsigned char raw1[8];
    unsigned char raw2[8];
    unsigned char raw3[8];
    unsigned char safe1[8];
    unsigned char safe2[8];
    unsigned char safe3[8];
    
    klee_make_symbolic(raw1, sizeof(raw1), "raw1");
    klee_make_symbolic(raw2, sizeof(raw2), "raw2");
    klee_make_symbolic(raw3, sizeof(raw3), "raw3");
    
    make_ascii_word(safe1, raw1, 8);
    make_ascii_word(safe2, raw2, 8);
    make_ascii_word(safe3, raw3, 8);
    
    switch (klass) {
        case 0:
            // C1: Explicit document with directive
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "%YAML 1.2\n---\nkey: ");
            append_bytes(data, &len, LIBYAML_KLEE_MAX_INPUT, safe1, 8);
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "\n");
            break;
            
        case 1:
            // C2: Block collections with nesting
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "list:\n  - name: ");
            append_bytes(data, &len, LIBYAML_KLEE_MAX_INPUT, safe1, 8);
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "\n    items:\n      - ");
            append_bytes(data, &len, LIBYAML_KLEE_MAX_INPUT, safe2, 8);
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "\n");
            break;
            
        case 2:
            // C3: Flow collections
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "data: [");
            append_bytes(data, &len, LIBYAML_KLEE_MAX_INPUT, safe1, 8);
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, ", {key: ");
            append_bytes(data, &len, LIBYAML_KLEE_MAX_INPUT, safe2, 8);
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "}]\n");
            break;
            
        case 3:
            // C4: Anchors and aliases
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "anchor: &ref ");
            append_bytes(data, &len, LIBYAML_KLEE_MAX_INPUT, safe1, 8);
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "\nalias: *ref\n");
            break;
            
        case 4:
            // C5: Multi-document stream
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "first: ");
            append_bytes(data, &len, LIBYAML_KLEE_MAX_INPUT, safe1, 8);
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "\n...\n---\nsecond: ");
            append_bytes(data, &len, LIBYAML_KLEE_MAX_INPUT, safe2, 8);
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "\n");
            break;
            
        case 5:
            // C6: Malformed structure (missing colon)
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "key ");
            append_bytes(data, &len, LIBYAML_KLEE_MAX_INPUT, safe1, 8);
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "\nvalid: ");
            append_bytes(data, &len, LIBYAML_KLEE_MAX_INPUT, safe2, 8);
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "\n");
            break;
            
        case 6:
            // C7: Empty and minimal content
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "empty:\nkey: ");
            append_bytes(data, &len, LIBYAML_KLEE_MAX_INPUT, safe1, 8);
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "\nlist:\n  -\n  - ");
            append_bytes(data, &len, LIBYAML_KLEE_MAX_INPUT, safe2, 8);
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "\n");
            break;
            
        case 7:
            // C8: Deep nesting
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "a:\n  b:\n    c:\n      d:\n        e:\n          f: ");
            append_bytes(data, &len, LIBYAML_KLEE_MAX_INPUT, safe1, 8);
            append_str(data, &len, LIBYAML_KLEE_MAX_INPUT, "\n");
            break;
    }
    
    // Null terminate
    if (len < LIBYAML_KLEE_MAX_INPUT) {
        data[len] = '\0';
    }
    
    ok = yaml_parser_initialize(&parser);
    if (!ok) {
        return 0;
    }

    yaml_parser_set_input_string(&parser, data, len);
    yaml_set_max_nest_level(32);

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