#include <klee/klee.h>
#include "klee_extra.h"
// helper builders (small, bounded)

static void append_str(char **w, int *left, const char *s) {
    if (*left <= 1) return;
    int n = 0;
    while (s[n] && n < *left - 1) { **w = s[n]; (*w)++; n++; }
    **w = '\0';
    *left -= n;
}

static void append_repeat(char **w, int *left, char ch, int count) {
    if (*left <= 1) return;
    int i;
    for (i = 0; i < count && *left > 1; i++) { **w = ch; (*w)++; (*left)--; }
    **w = '\0';
}

static void append_int_token(char **w, int *left, const char *prefix, int v, const char *suffix) {
    char tmp[64];
    int n = 0;
    char *p = tmp;
    if (prefix) {
        while (*prefix && n < (int)sizeof(tmp) - 1) { tmp[n++] = *prefix++; }
    }
    // simple integer to string
    int x = v, digits = 0, rev[16];
    if (x == 0) rev[digits++] = 0;
    while (x > 0 && digits < 16) { rev[digits++] = x % 10; x /= 10; }
    while (digits > 0 && n < (int)sizeof(tmp) - 1) { tmp[n++] = (char)('0' + rev[--digits]); }
    if (suffix) {
        while (*suffix && n < (int)sizeof(tmp) - 1) { tmp[n++] = *suffix++; }
    }
    tmp[n] = '\0';
    append_str(w, left, tmp);
}

// Unknown encoding handler for C5: accept a custom encoding name and provide ASCII mapping
static int unknownEncHandler(void *encHandlerData, const XML_Char *name, XML_Encoding *info) {
    (void)encHandlerData;
    (void)name;
    int i;
    for (i = 0; i < 256; i++) {
        // Map ASCII 0..127 to themselves; mark others as unmapped (0)
        info->map[i] = (i < 128) ? i : 0;
    }
    info->data = NULL;
    info->convert = NULL; // no custom converter
    info->release = NULL; // nothing to free
    return 1; // handled
}

// External entity handler for C7: create child parser and parse a minimal entity
static int externalEntityRefHandler(XML_Parser parser,
                                    const XML_Char *context,
                                    const XML_Char *base,
                                    const XML_Char *systemId,
                                    const XML_Char *publicId) {
    (void)base;
    (void)systemId;
    (void)publicId;
    XML_Parser child = XML_ExternalEntityParserCreate(parser, context, NULL);
    if (!child) return 0;
    const char childBuf[] = "<child/>"; // minimal child content
    XML_Parse(child, childBuf, (int)sizeof(childBuf) - 1, 1);
    XML_ParserFree(child);
    return 1;
}

int main(int argc, char **argv) {
    int klass = klee_range(1, 8, "klass");
    switch (klass) {

        // C1. Parser initialization before any input (pre-scan, countBytesDirect == 0)
        case 1: {
            XML_Parser p = XML_ParserCreate(NULL);
            if (!p) return 0;
            // No bytes scanned, but invoke parse once to drive state without input
            XML_Parse(p, "", 0, 0);
            XML_ParserFree(p);
            break;
        }

        // C2. Oversized token/value causing pool/buffer growth (long attribute value)
        case 2: {
            char buf[4096]; char *w = buf; int left = (int)sizeof(buf); *w = '\0';
            int L = klee_range(256, 3072, "long_token_len");
            append_str(&w, &left, "<r a='");
            append_repeat(&w, &left, 'A', L);
            append_str(&w, &left, "'/>");
            XML_Parser p = XML_ParserCreate(NULL);
            if (!p) return 0;
            XML_Parse(p, buf, (int)strlen(buf), 1);
            XML_ParserFree(p);
            break;
        }

        // C3. Large attribute/namespace sets in one start tag
        case 3: {
            char buf[8192]; char *w = buf; int left = (int)sizeof(buf); *w = '\0';
            int numAttrs = klee_range(20, 80, "num_attrs");
            append_str(&w, &left, "<root xmlns:a='urn:a' xmlns:b='urn:b' xmlns='urn:def'");
            for (int i = 0; i < numAttrs; i++) {
                append_str(&w, &left, " ");
                append_int_token(&w, &left, "a", i, "='");
                append_int_token(&w, &left, "", i, "'");
            }
            append_str(&w, &left, "></root>");
            XML_Parser p = XML_ParserCreate(NULL);
            if (!p) return 0;
            XML_Parse(p, buf, (int)strlen(buf), 1);
            XML_ParserFree(p);
            break;
        }

        // C4. High-amplification entity expansion via internal DTD
        case 4: {
            char buf[8192]; char *w = buf; int left = (int)sizeof(buf); *w = '\0';
            int repsA = klee_range(16, 64, "entity_a_len"); // base entity size
            int repsB = klee_range(8, 24, "entity_b_refs"); // number of &a; in b
            append_str(&w, &left, "<!DOCTYPE r [ <!ENTITY a \"");
            append_repeat(&w, &left, 'x', repsA);
            append_str(&w, &left, "\"> <!ENTITY b \"");
            for (int i = 0; i < repsB; i++) append_str(&w, &left, "&a;");
            append_str(&w, &left, "\"> <!ENTITY c \"");
            for (int i = 0; i < 8; i++) append_str(&w, &left, "&b;");
            append_str(&w, &left, "\"> ]><r>&c;</r>");
            XML_Parser p = XML_ParserCreate(NULL);
            if (!p) return 0;
            XML_Parse(p, buf, (int)strlen(buf), 1);
            XML_ParserFree(p);
            break;
        }

        // C5. Unknown/custom encoding negotiation
        case 5: {
            XML_Parser p = XML_ParserCreate(NULL);
            if (!p) return 0;
            XML_SetUnknownEncodingHandler(p, unknownEncHandler, NULL);
            const char buf[] = "<?xml version='1.0' encoding='X-KLEE-ENC'?><r/>";
            XML_Parse(p, buf, (int)sizeof(buf) - 1, 1);
            XML_ParserFree(p);
            break;
        }

        // C6. Early fatal error with teardown (malformed token to trigger immediate abort)
        case 6: {
            const char buf[] = "<r><"; // incomplete second element start -> error
            XML_Parser p = XML_ParserCreate(NULL);
            if (!p) return 0;
            XML_Parse(p, buf, (int)sizeof(buf) - 1, 1);
            XML_ParserFree(p);
            break;
        }

        // C7. External entity inclusion creating child parsers
        case 7: {
            XML_Parser p = XML_ParserCreate(NULL);
            if (!p) return 0;
            XML_SetExternalEntityRefHandler(p, externalEntityRefHandler);
            const char buf[] = "<!DOCTYPE r [ <!ENTITY ext SYSTEM 'ext.xml'> ]><r>&ext;</r>";
            XML_Parse(p, buf, (int)sizeof(buf) - 1, 1);
            XML_ParserFree(p);
            break;
        }

        default:
            break;
    }

    return 0;
}