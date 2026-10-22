#include "klee_extra.h"
#include <expat.h>
#include <klee/klee.h>
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <stdlib.h>
#define set_env(k, v) _putenv_s((k), (v))
#else
#include <unistd.h>
#define set_env(k, v) setenv((k), (v), 1)
#endif

// Global controls for custom allocator behavior
static int g_fail_after = -1;   // -1 means never fail; otherwise fail when this hits 0
static int g_call_count = 0;    // count of malloc+realloc calls

static void *suite_malloc(size_t size) {
  if (g_fail_after >= 0) {
    if (g_call_count >= g_fail_after) {
      return NULL;
    }
    g_call_count++;
  }
  return malloc(size);
}

static void *suite_realloc(void *ptr, size_t size) {
  if (g_fail_after >= 0) {
    if (g_call_count >= g_fail_after) {
      // Simulate failure independent of size to hit external allocator failure paths
      return NULL;
    }
    g_call_count++;
  }
  // Honor C semantics: realloc(ptr, 0) == free(ptr) + return NULL
  if (size == 0) {
    free(ptr);
    return NULL;
  }
  return realloc(ptr, size);
}

static void suite_free(void *ptr) {
  free(ptr);
}

// Helper to optionally create a parser with a custom allocator suite
static XML_Parser make_parser_with_suite(int use_suite) {
  if (!use_suite) {
    return XML_ParserCreate(NULL);
  } else {
    XML_Memory_Handling_Suite ms;
    ms.malloc_fcn = suite_malloc;
    ms.realloc_fcn = suite_realloc;
    ms.free_fcn = suite_free;
    return XML_ParserCreate_MM(NULL, &ms, NULL);
  }
}

int main(int argc, char **argv) {
  // Choose a semantic class to build a bounded but diverse space
  int klass = klee_range(1, 10, "klass"); // 1..9

  // Some small symbolic XML input buffer used by cases that want a parse call with content
  char xml_buf[64];
  klee_make_symbolic(xml_buf, sizeof(xml_buf), "xml_buf_sym");
  // Provide a minimal well-formed default skeleton where needed; overwritten per case as needed
  const char default_xml[] = "<a/>";
  memcpy(xml_buf, default_xml, sizeof(default_xml)); // includes '\0' at end

  XML_Parser p = NULL;

  switch (klass) {
    case 1: {
      // C1: Allocation-size integer overflow boundary attempt via huge GetBuffer request
      g_fail_after = -1; g_call_count = 0;
      p = make_parser_with_suite(1);
      if (!p) return 0;

      // Request a very large buffer near INT_MAX to stress internal size additions
      int huge = klee_range(INT_MAX - 1024, INT_MAX, "c1_huge");
      (void)XML_GetBuffer(p, huge);

      // Ensure we call XML_Parse once; use empty final parse
      XML_Parse(p, "", 0, 1);
      XML_ParserFree(p);
      break;
    }

    case 2: {
      // C2: Accounting accumulator overflow attempt via large increase between reallocs
      g_fail_after = -1; g_call_count = 0;
      p = make_parser_with_suite(1);
      if (!p) return 0;

      int a1 = klee_range(1 << 20, (1 << 22) + 1, "c2_a1"); // ~1-4 MiB
      int a2 = klee_range(INT_MAX / 3, INT_MAX / 2, "c2_a2"); // large jump
      (void)XML_GetBuffer(p, a1);
      (void)XML_GetBuffer(p, a2);

      XML_Parse(p, "", 0, 1);
      XML_ParserFree(p);
      break;
    }

    case 3: {
      // C3: Activation threshold and amplification logic stress (divide-by-zero risk)
      // We try to amplify by going from tiny to huge and enable allocator debug if supported.
      set_env("EXPAT_ALLOC_DEBUG", "2");
      g_fail_after = -1; g_call_count = 0;
      p = make_parser_with_suite(1);
      if (!p) return 0;

      (void)XML_GetBuffer(p, 1); // minimal
      int big = klee_range(1 << 24, (1 << 27), "c3_big"); // 16-128 MiB
      (void)XML_GetBuffer(p, big);

      XML_Parse(p, "", 0, 1);
      XML_ParserFree(p);
      break;
    }

    case 4: {
      // C4: External allocator failure (malloc/realloc callbacks return NULL)
      // Delay failure until a post-creation allocation happens.
      g_call_count = 0;
      g_fail_after = klee_range(1, 4, "c4_fail_after"); // fail on Nth allocation
      p = make_parser_with_suite(1);
      if (!p) return 0;

      // Trigger an allocation that may fail
      int req = klee_range(1024, 8192, "c4_req");
      (void)XML_GetBuffer(p, req);

      XML_Parse(p, "", 0, 1);
      XML_ParserFree(p);
      break;
    }

    case 5: {
      // C5: Realloc edge topologies (NULL ptr, zero size, size change bookkeeping)
      g_fail_after = -1; g_call_count = 0;
      p = make_parser_with_suite(1);
      if (!p) return 0;

      // Exercise initial allocation (may be realloc(NULL, size) internally)
      (void)XML_GetBuffer(p, 0);   // zero-size request
      (void)XML_GetBuffer(p, 16);  // small non-zero size
      (void)XML_GetBuffer(p, 0);   // zero again to encourage free+NULL in realloc path

      XML_Parse(p, "", 0, 1);
      XML_ParserFree(p);
      break;
    }

    case 6: {
      // C6: High debug-level accounting and peak tracking
      set_env("EXPAT_ALLOC_DEBUG", "2");
      g_fail_after = -1; g_call_count = 0;
      p = make_parser_with_suite(1);
      if (!p) return 0;

      (void)XML_GetBuffer(p, 64);
      (void)XML_GetBuffer(p, 4096); // cross a small "peak"
      XML_Parse(p, "", 0, 1);
      XML_ParserFree(p);
      break;
    }

    case 7: {
      // C7: Entropy via /dev/urandom provider (enable entropy debug if honored)
      set_env("EXPAT_ENTROPY_DEBUG", "1");
      p = make_parser_with_suite(0);
      if (!p) return 0;

      // Minimal parse to drive standard path
      XML_Parse(p, xml_buf, (int)strlen(xml_buf), 1);
      XML_ParserFree(p);
      break;
    }

    case 8: {
      // C8: Fallback entropy path (try to discourage high-quality provider)
      // These env vars are best-effort; library may ignore them but harmless.
      set_env("EXPAT_ENTROPY_DEBUG", "1");
      set_env("XML_DEV_URANDOM", "0");
      set_env("EXPAT_ENTROPY_URANDOM", "0");
      set_env("EXPAT_DISABLE_URANDOM", "1");

      p = make_parser_with_suite(0);
      if (!p) return 0;

      XML_Parse(p, xml_buf, (int)strlen(xml_buf), 1);
      XML_ParserFree(p);
      break;
    }

    case 9: {
      // C9: Partial-token reparse deferral path; finalBuffer=false and incomplete token
      p = make_parser_with_suite(0);
      if (!p) return 0;

      // Enable reparse deferral if API is available (Expat >= 2.6)
      #if defined(XML_MAJOR_VERSION) && defined(XML_MINOR_VERSION)
      #if (XML_MAJOR_VERSION > 2) || (XML_MAJOR_VERSION == 2 && XML_MINOR_VERSION >= 6)
      XML_SetReparseDeferralEnabled(p, XML_TRUE);
      #endif
      #endif

      // Incomplete token: "<a x='" with final=0
      const char partial[] = "<a x='";
      XML_Parse(p, partial, (int)sizeof(partial) - 1, 0);
      XML_ParserFree(p);
      break;
    }

    default: {
      // Fallback: simple parse using default allocator (should not be reached)
      p = make_parser_with_suite(0);
      if (!p) return 0;
      XML_Parse(p, xml_buf, (int)strlen(xml_buf), 1);
      XML_ParserFree(p);
      break;
    }
  }

  return 0;
}