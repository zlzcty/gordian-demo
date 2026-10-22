#include <klee/klee.h>
#include <yaml.h>

#define LIBYAML_KLEE_MAX_INPUT 256
#define LIBYAML_KLEE_MAX_TOKENS 512

int main(void)
{
    yaml_parser_t parser;
    yaml_token_t token;
    unsigned char data[LIBYAML_KLEE_MAX_INPUT];
    unsigned int count = 0;
    int ok;

    klee_make_symbolic(data, sizeof(data), "yaml_input");

    ok = yaml_parser_initialize(&parser);
    if (!ok) {
        return 0;
    }

    yaml_parser_set_input_string(&parser, data, sizeof(data));
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
