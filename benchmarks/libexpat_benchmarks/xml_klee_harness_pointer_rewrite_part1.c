#include "klee_extra.h"
#include <expat.h>
#include <klee/klee.h>
#include <stdint.h>
#include <string.h>

/* Simple bounded string builder */
static void sb_append(char *buf, size_t cap, size_t *off, const char *s) {
    if (*off >= cap) return;
    size_t n = strlen(s);
    if (*off + n >= cap) {
        n = (cap - 1 > *off) ? (cap - 1 - *off) : 0;
    }
    if (n > 0) {
        memcpy(buf + *off, s, n);
        *off += n;
    }
    buf[*off] = '\0';
}

static void sb_append_uint(char *buf, size_t cap, size_t *off, unsigned v) {
    char tmp[32];
    unsigned i = 0;
    if (v == 0) {
        tmp[i++] = '0';
    } else {
        char rev[32];
        unsigned j = 0;
        while (v > 0 && j < sizeof(rev)) {
            rev[j++] = (char)('0' + (v % 10));
            v /= 10;
        }
        while (j > 0) tmp[i++] = rev[--j];
    }
    tmp[i] = '\0';
    sb_append(buf, cap, off, tmp);
}

static int pick_one_of_three(const char *name) {
    int sel = klee_range(0, 3, name); /* returns 0, 1, or 2 */
    return sel;
}

int main(int argc, char **argv) {
    /* Construct targeted XML inputs per semantic case to drive hashtable probing */
    enum { CAP = 32768 };
    char doc[CAP];
    size_t off = 0;

    int klass = klee_range(1, 6, "klass"); /* 1..5 */

    /* Use namespaces when cases require it (C4, C5). */
    XML_Parser p = NULL;
    if (klass == 4 || klass == 5) {
        p = XML_ParserCreateNS(NULL, '|'); /* enable namespace processing */
    } else {
        p = XML_ParserCreate(NULL);
    }
    if (!p) return 0;

    /* Fix hash salt for determinism (still exercises probing on dense tables). */
    XML_SetHashSalt(p, (unsigned long)0u);

    /* Build per-case inputs */
    switch (klass) {
        case 1: {
            /* C1. Element-type name pressure: many distinct element names under one root */
            int sel = pick_one_of_three("c1_count_sel"); /* 0,1,2 -> 16, 32, 64 names */
            unsigned nNames = (sel == 0) ? 16u : (sel == 1) ? 32u : 64u;

            sb_append(doc, CAP, &off, "<r>");
            for (unsigned i = 0; i < nNames; ++i) {
                sb_append(doc, CAP, &off, "<n");
                sb_append_uint(doc, CAP, &off, i);
                sb_append(doc, CAP, &off, "/>");
            }
            sb_append(doc, CAP, &off, "</r>");
            break;
        }
        case 2: {
            /* C2. Attribute ID pressure: one element with many distinct attribute names */
            int sel = pick_one_of_three("c2_count_sel"); /* 0,1,2 -> 24, 48, 96 attributes */
            unsigned nAttrs = (sel == 0) ? 24u : (sel == 1) ? 48u : 96u;

            sb_append(doc, CAP, &off, "<r><e ");
            for (unsigned i = 0; i < nAttrs; ++i) {
                sb_append(doc, CAP, &off, "a");
                sb_append_uint(doc, CAP, &off, i);
                sb_append(doc, CAP, &off, "='v' ");
            }
            sb_append(doc, CAP, &off, "/></r>");
            break;
        }
        case 3: {
            /* C3. Entity name pressure (general +, optionally, parameter entities) via internal DTD */
            int sel = pick_one_of_three("c3_count_sel"); /* 0,1,2 -> 16, 32, 64 general entities */
            unsigned nGen = (sel == 0) ? 16u : (sel == 1) ? 32u : 64u;
            unsigned nPar = (sel == 0) ? 4u : (sel == 1) ? 8u : 16u;

            sb_append(doc, CAP, &off, "<!DOCTYPE r [");
            for (unsigned i = 0; i < nGen; ++i) {
                sb_append(doc, CAP, &off, "<!ENTITY e");
                sb_append_uint(doc, CAP, &off, i);
                sb_append(doc, CAP, &off, " 'g'>");
            }
            for (unsigned i = 0; i < nPar; ++i) {
                /* Parameter entities parsed if XML_DTD is enabled; harmless otherwise */
                sb_append(doc, CAP, &off, "<!ENTITY % p");
                sb_append_uint(doc, CAP, &off, i);
                sb_append(doc, CAP, &off, " 'p'>");
            }
            sb_append(doc, CAP, &off, "]><r/>");
            break;
        }
        case 4: {
            /* C4. Namespace prefix pressure: many distinct xmlns prefixes and uses */
            int sel = pick_one_of_three("c4_count_sel"); /* 0,1,2 -> 16, 32, 48 prefixes */
            unsigned nPref = (sel == 0) ? 16u : (sel == 1) ? 32u : 48u;

            sb_append(doc, CAP, &off, "<r ");
            for (unsigned i = 0; i < nPref; ++i) {
                sb_append(doc, CAP, &off, "xmlns:p");
                sb_append_uint(doc, CAP, &off, i);
                sb_append(doc, CAP, &off, "='urn:u");
                sb_append_uint(doc, CAP, &off, i);
                sb_append(doc, CAP, &off, "' ");
            }
            sb_append(doc, CAP, &off, ">");
            for (unsigned i = 0; i < nPref; ++i) {
                sb_append(doc, CAP, &off, "<p");
                sb_append_uint(doc, CAP, &off, i);
                sb_append(doc, CAP, &off, ":x/>");
            }
            sb_append(doc, CAP, &off, "</r>");
            break;
        }
        case 5: {
            /* C5. Near-capacity stress to encourage rehash/reinsert and probing across tables */
            int sel = pick_one_of_three("c5_count_sel"); /* 0,1,2 -> low/med/high */
            unsigned nGen  = (sel == 0) ? 24u  : (sel == 1) ? 48u  : 96u;  /* entities */
            unsigned nPar  = (sel == 0) ? 8u   : (sel == 1) ? 16u  : 32u;  /* param entities */
            unsigned nPref = (sel == 0) ? 16u  : (sel == 1) ? 32u  : 48u;  /* prefixes */
            unsigned nAttr = (sel == 0) ? 48u  : (sel == 1) ? 96u  : 160u; /* attributes */
            unsigned nElem = (sel == 0) ? 24u  : (sel == 1) ? 48u  : 80u;  /* distinct element names */

            /* Internal DTD with many entity declarations */
            sb_append(doc, CAP, &off, "<!DOCTYPE r [");
            for (unsigned i = 0; i < nGen; ++i) {
                sb_append(doc, CAP, &off, "<!ENTITY g");
                sb_append_uint(doc, CAP, &off, i);
                sb_append(doc, CAP, &off, " 'G'>");
            }
            for (unsigned i = 0; i < nPar; ++i) {
                sb_append(doc, CAP, &off, "<!ENTITY % q");
                sb_append_uint(doc, CAP, &off, i);
                sb_append(doc, CAP, &off, " 'Q'>");
            }
            sb_append(doc, CAP, &off, "]>");

            /* Root with many namespace prefixes */
            sb_append(doc, CAP, &off, "<r ");
            for (unsigned i = 0; i < nPref; ++i) {
                sb_append(doc, CAP, &off, "xmlns:n");
                sb_append_uint(doc, CAP, &off, i);
                sb_append(doc, CAP, &off, "='urn:n");
                sb_append_uint(doc, CAP, &off, i);
                sb_append(doc, CAP, &off, "' ");
            }
            sb_append(doc, CAP, &off, ">");

            /* One element with many attributes (attributeIds table) */
            sb_append(doc, CAP, &off, "<e ");
            for (unsigned i = 0; i < nAttr; ++i) {
                sb_append(doc, CAP, &off, "k");
                sb_append_uint(doc, CAP, &off, i);
                sb_append(doc, CAP, &off, "='v' ");
            }
            sb_append(doc, CAP, &off, "/>");

            /* Many distinct element names (elementTypes table) */
            for (unsigned i = 0; i < nElem; ++i) {
                sb_append(doc, CAP, &off, "<t");
                sb_append_uint(doc, CAP, &off, i);
                sb_append(doc, CAP, &off, "/>");
            }

            /* Use some prefixes to exercise prefix lookup/insert path */
            for (unsigned i = 0; i < (nPref > 8 ? 8 : nPref); ++i) {
                sb_append(doc, CAP, &off, "<n");
                sb_append_uint(doc, CAP, &off, i);
                sb_append(doc, CAP, &off, ":z/>");
            }

            sb_append(doc, CAP, &off, "</r>");
            break;
        }
        default:
            break;
    }

    /* Parse the constructed document in one chunk */
    XML_Parse(p, doc, (int)off, 1);
    XML_ParserFree(p);
    return 0;
}