#include "klee_extra.h"
#include <expat.h>
#include <klee/klee.h>
#include <string.h>
#include <stdlib.h>

/* Helper: simple conversion for unknown encoding handler
   Identity mapping for ASCII 0x00..0x7F; others unmapped (-1) */
static int unk_convert(void *data, const char *s) {
    (void)data;
    (void)s;
    /* Returning 0 indicates conversion failure for given sequence,
       which is fine for our purposes here. */
    return 0;
}

/* Helper: release hook for unknown encoding */
static void unk_release(void *data) {
    volatile int *flag = (volatile int *)data;
    if (flag) *flag = 1;
}

/* Unknown encoding handler to install a release hook */
static int unknown_encoding_handler(void *userData, const XML_Char *name, XML_Encoding *info) {
    (void)name;
    /* Initialize map: identity for ASCII, -1 for others */
    for (int i = 0; i < 256; ++i) info->map[i] = -1;
    for (int i = 0; i < 128; ++i) info->map[i] = i;
    info->data = userData;
    info->convert = unk_convert;
    info->release = unk_release;
    return 1; /* success */
}

/* Busy-parse start element handler: attempt feature changes while parserBusy(parser) == true */
static void busy_start_handler(void *userData, const XML_Char *name, const XML_Char **atts) {
    (void)name; (void)atts;
    XML_Parser p = (XML_Parser)userData;
    /* These should exercise "busy" error guards in respective APIs */
    XML_SetEncoding(p, "us-ascii");
    XML_UseForeignDTD(p, XML_TRUE);
    XML_SetReturnNSTriplet(p, 1);
}

/* Helper: minimal parse to satisfy "call XML_Parse once" when needed */
static void do_minimal_parse(XML_Parser p) {
    const char *doc = "<a/>";
    XML_Parse(p, doc, (int)strlen(doc), 1);
}

int main(int argc, char **argv) {
    (void)argc; (void)argv;

    int klass = klee_range(1, 9, "klass");

    switch (klass) {
        case 1: {
            /* C1. NULL parser pointer at API entry: hit early guards */
            XML_SetEncoding(NULL, "utf-8");
            XML_UseForeignDTD(NULL, XML_TRUE);
            XML_SetReturnNSTriplet(NULL, 1);
            XML_SetUserData(NULL, (void *)0x1);
            XML_SetBase(NULL, "base");
            (void)XML_GetBase(NULL);
            (void)XML_GetSpecifiedAttributeCount(NULL);
            (void)XML_GetIdAttributeIndex(NULL);
            XML_ParserFree(NULL);

            /* Still call XML_Parse once on a valid parser */
            XML_Parser p = XML_ParserCreate(NULL);
            if (!p) break;
            XML_Parse(p, "", 0, 1);
            XML_ParserFree(p);
            break;
        }

        case 2: {
            /* C2. Idle and finished state paths via XML_ResumeParser */
            XML_Parser p_idle = XML_ParserCreate(NULL);
            if (p_idle) {
                /* Idle (XML_INITIALIZED) */
                (void)XML_ResumeParser(p_idle);
                XML_ParserFree(p_idle);
            }

            XML_Parser p_finished = XML_ParserCreate(NULL);
            if (p_finished) {
                /* Drive to FINISHED with an empty final parse */
                XML_Parse(p_finished, "", 0, 1);
                (void)XML_ResumeParser(p_finished);
                XML_ParserFree(p_finished);
            }
            break;
        }

        case 3: {
            /* C3. Mid-parse (busy) feature change attempts inside a callback */
            XML_Parser p = XML_ParserCreate(NULL);
            if (!p) break;
            XML_SetUserData(p, p);
            XML_SetStartElementHandler(p, busy_start_handler);
            const char *doc = "<a/>";
            XML_Parse(p, doc, (int)strlen(doc), 1);
            XML_ParserFree(p);
            break;
        }

        case 4: {
            /* C4. External general entity parser creation with namespaces and handler-arg alias */
            XML_Parser old = XML_ParserCreateNS(NULL, '|');
            if (!old) break;

            /* Ensure m_handlerArg == m_userData by setting user data */
            int user_blob = 0;
            XML_SetUserData(old, &user_blob);

            /* Ensure external entity handler arg != old parser */
            int ee_arg_blob = 0;
            XML_SetExternalEntityRefHandlerArg(old, &ee_arg_blob);

            const XML_Char *ctx = "extCtx";
            XML_Parser child = XML_ExternalEntityParserCreate(old, ctx, NULL);
            if (child) {
                XML_ParserFree(child);
            }

            /* Minimal parse to exercise parser state */
            do_minimal_parse(old);
            XML_ParserFree(old);
            break;
        }

        case 5: {
            /* C5. External parameter entity parser creation without namespaces (context == NULL) */
            XML_Parser old = XML_ParserCreate(NULL); /* namespaces disabled */
            if (!old) break;

            XML_Parser child = XML_ExternalEntityParserCreate(old, NULL, NULL);
            if (child) {
                XML_ParserFree(child);
            }

            do_minimal_parse(old);
            XML_ParserFree(old);
            break;
        }

        case 6: {
            /* C6. Attempt external entity creation failure path */
            XML_Parser old = XML_ParserCreateNS(NULL, ':');
            if (!old) break;

            /* Build a symbolic context string (bounded) */
            char ctx[64];
            klee_make_symbolic(ctx, sizeof(ctx), "ext_ctx");
            /* Ensure NUL termination to keep it safe */
            ctx[sizeof(ctx) - 1] = '\0';

            XML_Parser child = XML_ExternalEntityParserCreate(old, ctx, NULL);
            if (child) {
                XML_ParserFree(child);
            }

            do_minimal_parse(old);
            XML_ParserFree(old);
            break;
        }

        case 7: {
            /* C7. Teardown after parsing with unknown encoding release and namespace bindings */
            XML_Parser p = XML_ParserCreateNS(NULL, '|');
            if (!p) break;

            volatile int released = 0;
            XML_SetUnknownEncodingHandler(p, unknown_encoding_handler, (void *)&released);

            /* XML with unknown encoding and some namespace bindings */
            const char *xml =
                "<?xml version='1.0' encoding='X-UNK'?>"
                "<a xmlns='urn:x' xmlns:ns='urn:y'><ns:b/></a>";
            XML_Parse(p, xml, (int)strlen(xml), 1);

            XML_ParserFree(p);
            /* released flag is set by unk_release during free if handler installed */
            (void)released;
            break;
        }

        case 8: {
            /* C8. Non-busy feature mutations and alias divergence */
            XML_Parser p = XML_ParserCreate(NULL);
            if (!p) break;

            /* Encoding set then cleared */
            XML_SetEncoding(p, "latin1");
            XML_SetEncoding(p, NULL);

            /* Foreign DTD flag */
            XML_UseForeignDTD(p, XML_TRUE);

            /* Return NS triplet setting (no namespaces here, but toggled) */
            XML_SetReturnNSTriplet(p, 1);

            /* User data and handler arg alias toggling */
            int ud1 = 0, ud2 = 0;
            XML_SetUserData(p, &ud1);           /* m_handlerArg == m_userData */
            XML_UseParserAsHandlerArg(p);       /* m_handlerArg == parser (alias diverges) */
            XML_SetUserData(p, &ud2);           /* back to user data as handler arg */

            /* Base URI into DTD pool */
            (void)XML_SetBase(p, "http://example/base/");

            /* Minimal parse and free */
            XML_Parse(p, "", 0, 1);
            XML_ParserFree(p);
            break;
        }

        default: {
            /* Fallback: do a simple parse to keep entrypoint exercised */
            XML_Parser p = XML_ParserCreate(NULL);
            if (p) {
                do_minimal_parse(p);
                XML_ParserFree(p);
            }
            break;
        }
    }

    return 0;
}