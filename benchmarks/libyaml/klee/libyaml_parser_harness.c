#include <klee/klee.h>
#include <yaml.h>

#define LIBYAML_KLEE_MAX_INPUT 256
#define LIBYAML_KLEE_MAX_EVENTS 512

int main(void)
{
    yaml_parser_t parser;
    yaml_event_t event;
    unsigned char data[LIBYAML_KLEE_MAX_INPUT];
    unsigned int count = 0;
    int ok;

    klee_make_symbolic(data, sizeof(data), "yaml_input");

    ok = yaml_parser_initialize(&parser);
    if (!ok) {
        return 0;
    }

    yaml_parser_set_input_string(&parser, data, sizeof(data));
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
