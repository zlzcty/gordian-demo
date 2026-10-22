#include "klee_extra.h"
#include <expat.h>
#include <klee/klee.h>
#include <stdlib.h>
#include <string.h>

/* Custom memory suite with controllable failure to exercise C5/C6/C7 */
static int g_fail_alloc_at = 0;   /* 1-based index of allocation to fail; 0 = never fail */
static int g_alloc_count   = 0;   /* counts total allocations across parser(s) */

static void *ms_malloc(size_t sz) {
    g_alloc_count++;
    if (g_fail_alloc_at == g_alloc_count) {
        return NULL;
    }
    return malloc(sz);
}
static void *ms_realloc(void *p, size_t sz) {
    /* keep realloc simple: do not simulate failure here by default */
    return realloc(p, sz);
}
static void ms_free(void *p) {
    free(p);
}

/* C2: stop parser from a handler to force SUSPENDED path */
static void XMLCALL on_start_stop(void *userData, const XML_Char *name, const XML_Char **atts) {
    XML_Parser p = (XML_Parser)userData;
    XML_StopParser(p, XML_TRUE);
}

/* C3: attempt re-entrant parsing from handler to provoke error-on-reenter */
static int g_reenter_triggered = 0;
static void XMLCALL on_start_reenter(void *userData, const XML_Char *name, const XML_Char **atts) {
    if (g_reenter_triggered) return;
    g_reenter_triggered = 1;
    XML_Parser p = (XML_Parser)userData;
    const char inner[] = "<inner/>";
    /* Calling XML_Parse while already in a handler should trigger a non-success path */
    (void)XML_Parse(p, inner, (int)sizeof(inner) - 1, XML_TRUE);
}

/* C8: unknown encoding handler with a release callback to exercise release/reset paths */
static void XMLCALL on_unknown_encoding_release(void *data) {
    free(data);
}
static int XMLCALL on_unknown_encoding(void *encodingHandlerData,
                                       const XML_Char *name,
                                       XML_Encoding *info) {
    /* Provide a simple 1-byte identity mapping for ASCII; others unmapped */
    int i;
    for (i = 0; i < 256; ++i) info->map[i] = -1;
    for (i = 0; i < 128; ++i) info->map[i] = i;

    info->convert = NULL;
    /* Allocate a tiny block so that release() has something to free */
    info->data = malloc(8);
    info->release = on_unknown_encoding_release;
    return XML_STATUS_OK;
}

/* Helper for C1: write up to 'n' characters into Expat's internal buffer */
static void fill_minimal_xml_fragment(char *dst, int n, int variant) {
    /* Provide tiny fragments that can be stitched across multiple ParseBuffer calls */
    if (n <= 0) return;
    switch (variant % 3) {
        case 0:
            /* just a start of a tag "<a" */
            if (n >= 1) dst[0] = '<';
            if (n >= 2) dst[1] = 'a';
            if (n >= 3) dst[2] = '\0';
            break;
        case 1:
            /* close the tag ">" */
            dst[0] = '>';
            if (n >= 2) dst[1] = '\0';
            break;
        default:
            /* self-close "/>" */
            if (n >= 1) dst[0] = '/';
            if (n >= 2) dst[1] = '>';
            if (n >= 3) dst[2] = '\0';
            break;
    }
}

int main(int argc, char **argv) {
    int klass = klee_range(1, 9, "klass"); /* choose 1..8 */

    switch (klass) {
        case 1: {
            /* C1. Deferred reparse gating with insufficient growth via GetBuffer/ParseBuffer */
            XML_Parser p = XML_ParserCreate(NULL);
            if (!p) return 0;

            /* Request tiny buffers with small or zero growth to tickle the gating heuristic */
            int v1 = klee_range(0, 3, "c1_v1"); /* choose fragment variant */
            int l1 = klee_range(0, 3, "c1_l1"); /* request size 0..2 */
            char *b1 = (char *)XML_GetBuffer(p, l1);
            if (b1 && l1 > 0) {
                fill_minimal_xml_fragment(b1, l1, v1);
            }
            XML_ParseBuffer(p, l1, XML_FALSE);

            int v2 = klee_range(0, 3, "c1_v2");
            int l2 = klee_range(0, 3, "c1_l2"); /* same or smaller to make growth "not enough" */
            char *b2 = (char *)XML_GetBuffer(p, l2);
            if (b2 && l2 > 0) {
                fill_minimal_xml_fragment(b2, l2, v2);
            }
            XML_ParseBuffer(p, l2, klee_range(0, 2, "c1_final2")); /* final 0 or 1 */

            /* Final tiny push to complete or not */
            int v3 = klee_range(0, 3, "c1_v3");
            int l3 = klee_range(0, 2, "c1_l3");
            char *b3 = (char *)XML_GetBuffer(p, l3);
            if (b3 && l3 > 0) {
                fill_minimal_xml_fragment(b3, l3, v3);
            }
            XML_ParseBuffer(p, l3, XML_TRUE);

            XML_ParserFree(p);
            break;
        }

        case 2: {
            /* C2. Suspension takes precedence over re-enter */
            XML_Parser p = XML_ParserCreate(NULL);
            if (!p) return 0;
            XML_SetUserData(p, p);
            XML_SetStartElementHandler(p, on_start_stop);

            const char xml[] = "<a><b/></a>";
            (void)XML_Parse(p, xml, (int)sizeof(xml) - 1, XML_TRUE);

            XML_ParserFree(p);
            break;
        }

        case 3: {
            /* C3. Error on re-enter path by calling XML_Parse from inside a handler */
            XML_Parser p = XML_ParserCreate(NULL);
            if (!p) return 0;
            g_reenter_triggered = 0;
            XML_SetUserData(p, p);
            XML_SetStartElementHandler(p, on_start_reenter);

            const char xml[] = "<a/>";
            (void)XML_Parse(p, xml, (int)sizeof(xml) - 1, XML_TRUE);

            XML_ParserFree(p);
            break;
        }

        case 4: {
            /* C4. Namespaces enabled at start */
            XML_Parser p = XML_ParserCreateNS(NULL, (XML_Char)':');
            if (!p) return 0;

            const char xml[] = "<ns:root xmlns:ns='urn:x'><ns:child/></ns:root>";
            (void)XML_Parse(p, xml, (int)sizeof(xml) - 1, XML_TRUE);

            XML_ParserFree(p);
            break;
        }

        case 5: {
            /* C5. Custom memory suite path */
            XML_Memory_Handling_Suite ms;
            ms.malloc_fcn  = ms_malloc;
            ms.realloc_fcn = ms_realloc;
            ms.free_fcn    = ms_free;

            g_alloc_count = 0;
            g_fail_alloc_at = 0; /* do not fail: exercise custom-ms normal path */

            XML_Parser p = XML_ParserCreate_MM(NULL, &ms, NULL);
            if (!p) return 0;

            char buf[32];
            klee_make_symbolic(buf, sizeof(buf), "c5_xml");
            /* Ensure some XML-ish skeleton to avoid trivial immediate errors */
            buf[0] = '<';
            buf[1] = 'a';
            buf[2] = '/';
            buf[3] = '>';
            (void)XML_Parse(p, buf, (int)sizeof(buf), XML_TRUE);

            XML_ParserFree(p);
            break;
        }

        case 6: {
            /* C6. Initial allocation failure of core buffers (simulate OOM during create) */
            XML_Memory_Handling_Suite ms;
            ms.malloc_fcn  = ms_malloc;
            ms.realloc_fcn = ms_realloc;
            ms.free_fcn    = ms_free;

            g_alloc_count = 0;
            g_fail_alloc_at = 2; /* let first allocation succeed, then fail on next core buffer */

            XML_Parser p = XML_ParserCreate_MM(NULL, &ms, NULL);
            /* Expect NULL and internal cleanups executed in create path */
            if (p) {
                XML_ParserFree(p);
            }
            break;
        }

        case 7: {
            /* C7. Child/external-entity parser creation under accounting constraints */
            XML_Memory_Handling_Suite ms;
            ms.malloc_fcn  = ms_malloc;
            ms.realloc_fcn = ms_realloc;
            ms.free_fcn    = ms_free;

            g_alloc_count = 0;
            g_fail_alloc_at = 0; /* allow parent to be created */
            XML_Parser parent = XML_ParserCreate_MM(NULL, &ms, NULL);
            if (!parent) return 0;

            /* Force the very next allocation (child creation) to fail */
            g_fail_alloc_at = g_alloc_count + 1;

            XML_Parser child = XML_ExternalEntityParserCreate(parent, NULL, NULL);
            if (child) {
                /* If creation succeeded despite our attempt, just parse a trivial token */
                const char xml[] = "<c/>";
                (void)XML_Parse(child, xml, (int)sizeof(xml) - 1, XML_TRUE);
                XML_ParserFree(child);
            }

            XML_ParserFree(parent);
            break;
        }

        case 8: {
            /* C8. Resetting a non-trivial parser state with unknown-encoding release */
            XML_Parser p = XML_ParserCreateNS(NULL, (XML_Char)':');
            if (!p) return 0;

            XML_SetUnknownEncodingHandler(p, on_unknown_encoding, NULL);

            /* Namespaced doc with unknown encoding declaration to trigger handler */
            const char xml[] =
                "<?xml version='1.0' encoding='X-FOO'?>"
                "<ns:root xmlns:ns='urn:x'><ns:child a='1'/></ns:root>";

            (void)XML_Parse(p, xml, (int)sizeof(xml) - 1, XML_TRUE);

            /* Now reset to force cleanup/migration and release() invocation */
            (void)XML_ParserReset(p, NULL);

            XML_ParserFree(p);
            break;
        }
    }

    return 0;
}