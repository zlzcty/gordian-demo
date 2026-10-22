#include <expat.h>
#include <klee/klee.h>
#include <string.h>

int main() {
    char buf[128];

    klee_make_symbolic(buf, sizeof(buf), "xml_input");

    XML_Parser p = XML_ParserCreate(NULL);
    if (!p) return 0;

    XML_Parse(p, buf, sizeof(buf), 1);
    XML_ParserFree(p);

    return 0;
}
