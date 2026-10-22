#include "/home/klee/klee_extra.h"
#include <klee/klee.h>
#include <yaml.h>
#include <string.h>

#define MAX_BUF 256
#define MAX_TOKENS 512

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
    yaml_token_t token;
    unsigned char data[MAX_BUF];
    size_t len = 0;
    unsigned int count = 0;
    int ok;

    unsigned char klass;
    klee_make_symbolic(&klass, sizeof(klass), "klass");
    klass = klass % 9;

    unsigned char raw1[6];
    unsigned char raw2[6];
    unsigned char safe1[6];
    unsigned char safe2[6];
    klee_make_symbolic(raw1, sizeof(raw1), "raw1");
    klee_make_symbolic(raw2, sizeof(raw2), "raw2");
    make_ascii_word(safe1, raw1, 6);
    make_ascii_word(safe2, raw2, 6);

    memset(data, 0, sizeof(data));

    switch (klass) {
    case 0:
        // Empty stream
        append_str(data, &len, MAX_BUF, "   \n# comment\n");
        break;
    case 1:
        // Directive processing
        append_str(data, &len, MAX_BUF, "%YAML 1.1\n%TAG !handle! prefix\n---\nkey: value\n");
        break;
    case 2:
        // Document markers
        append_str(data, &len, MAX_BUF, "---\nkey: value\n...\n");
        break;
    case 3:
        // Flow collections
        append_str(data, &len, MAX_BUF, "[");
        append_bytes(data, &len, MAX_BUF, safe1, 6);
        append_str(data, &len, MAX_BUF, ", ");
        append_bytes(data, &len, MAX_BUF, safe2, 6);
        append_str(data, &len, MAX_BUF, "]\n");
        break;
    case 4:
        // Flow mapping
        append_str(data, &len, MAX_BUF, "{");
        append_bytes(data, &len, MAX_BUF, safe1, 6);
        append_str(data, &len, MAX_BUF, ": ");
        append_bytes(data, &len, MAX_BUF, safe2, 6);
        append_str(data, &len, MAX_BUF, "}\n");
        break;
    case 5:
        // Block collections
        append_str(data, &len, MAX_BUF, "- ");
        append_bytes(data, &len, MAX_BUF, safe1, 6);
        append_str(data, &len, MAX_BUF, "\n- ");
        append_bytes(data, &len, MAX_BUF, safe2, 6);
        append_str(data, &len, MAX_BUF, "\n");
        break;
    case 6:
        // Scalar varieties
        append_str(data, &len, MAX_BUF, "plain: ");
        append_bytes(data, &len, MAX_BUF, safe1, 6);
        append_str(data, &len, MAX_BUF, "\nquoted: '");
        append_bytes(data, &len, MAX_BUF, safe2, 6);
        append_str(data, &len, MAX_BUF, "'\n");
        break;
    case 7:
        // Anchors and references
        append_str(data, &len, MAX_BUF, "anchor: &");
        append_bytes(data, &len, MAX_BUF, safe1, 6);
        append_str(data, &len, MAX_BUF, " value\nref: *");
        append_bytes(data, &len, MAX_BUF, safe1, 6);
        append_str(data, &len, MAX_BUF, "\n");
        break;
    case 8:
        // Invalid case - malformed flow
        append_str(data, &len, MAX_BUF, "[");
        append_bytes(data, &len, MAX_BUF, safe1, 6);
        append_str(data, &len, MAX_BUF, ", ");
        append_bytes(data, &len, MAX_BUF, safe2, 6);
        // Missing closing bracket
        break;
    }

    ok = yaml_parser_initialize(&parser);
    if (!ok) {
        return 0;
    }

    yaml_parser_set_input_string(&parser, data, len);
    while (count < MAX_TOKENS) {
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