#include "klee_extra.h"
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <klee/klee.h>

// Forward declaration of renamed main in the target program.
int real_main(int argc, const char* argv[]);

#define EXPR_MAX 256

// Leading digit policy for number builders
enum lead_policy {
  LEAD_ANY = 0,      // '0'..'9'
  LEAD_NONZERO,      // '1'..'9'
  LEAD_SMALL_NONZERO,// '1'..'4' (bias normalization-required paths)
  LEAD_LARGE         // '8'..'9' (bias no-normalization paths)
};

// Build a decimal integer string of exactly 'len' digits into 'out'.
// Characters are ASCII digits; the first digit is chosen according to 'policy'.
// The resulting string is NOT null-terminated by this function; caller should add '\0'.
static void build_symbolic_decimal(char *out, int len, const char *sym_name, enum lead_policy policy) {
  // Limit to a reasonable max
  if (len <= 0) return;
  // Make a temporary symbolic byte buffer
  unsigned char tmp[64];
  if (len > (int)sizeof(tmp)) len = (int)sizeof(tmp);

  klee_make_symbolic(tmp, (size_t)len, sym_name);

  // First digit policy
  switch (policy) {
    case LEAD_NONZERO:
      out[0] = (char)('1' + (tmp[0] % 9));      // '1'..'9'
      break;
    case LEAD_SMALL_NONZERO:
      out[0] = (char)('1' + (tmp[0] % 4));      // '1'..'4'
      break;
    case LEAD_LARGE:
      out[0] = (char)('8' + (tmp[0] % 2));      // '8'..'9'
      break;
    case LEAD_ANY:
    default:
      out[0] = (char)('0' + (tmp[0] % 10));     // '0'..'9'
      break;
  }

  // Remaining digits are free '0'..'9'
  for (int i = 1; i < len; ++i) {
    out[i] = (char)('0' + (tmp[i] % 10));
  }
}

// Build a decimal like 1 followed by 'zeros' zero digits (i.e., 10^zeros).
// Returns the length written.
static int build_pow10_like(char *out, int max_out, int zeros) {
  if (max_out <= 0) return 0;
  if (zeros + 1 >= max_out) zeros = max_out - 2; // leave room for '\0'
  out[0] = '1';
  for (int i = 1; i <= zeros; ++i) out[i] = '0';
  out[zeros + 1] = '\0';
  return zeros + 1;
}

int main(int argc, char **argv_unused) {
  char expr[EXPR_MAX];
  expr[0] = '\0';

  int klass = klee_range(1, 9, "klass"); // choose case 1..8

  switch (klass) {
    case 1: {
      // C1. Long division with multi-limb divisor requiring normalization.
      // Build large A and B as integers; B has small leading digit to bias normalization.
      char A[48], B[48];
      int alen = 36, blen = 28;
      build_symbolic_decimal(A, alen, "C1_A", LEAD_NONZERO);
      build_symbolic_decimal(B, blen, "C1_B", LEAD_SMALL_NONZERO);
      A[alen] = '\0'; B[blen] = '\0';
      // scale=0; A/B
      snprintf(expr, sizeof(expr), "scale=0; %s/%s", A, B);
      break;
    }
    case 2: {
      // C2. Long division where divisor effectively single-limb (one nonzero limb).
      // Use a power-of-10-like divisor (1 followed by many zeros) to concentrate value in one "limb".
      char A[40], B[64];
      int alen = 24;
      build_symbolic_decimal(A, alen, "C2_A", LEAD_NONZERO);
      A[alen] = '\0';
      build_pow10_like(B, (int)sizeof(B), 30); // "1" + 30 zeros
      snprintf(expr, sizeof(expr), "%s/%s", A, B);
      break;
    }
    case 3: {
      // C3. Long division with large multi-limb divisor (no normalization) and repeated subtraction.
      // Make B start with a high leading digit to bias "top limb > half" and make it multi-limb.
      char A[56], B[56];
      int alen = 40, blen = 32;
      build_symbolic_decimal(A, alen, "C3_A", LEAD_NONZERO);
      build_symbolic_decimal(B, blen, "C3_B", LEAD_LARGE);
      A[alen] = '\0'; B[blen] = '\0';
      snprintf(expr, sizeof(expr), "%s/%s", A, B);
      break;
    }
    case 4: {
      // C4. Fast-path integer-by-single-limb division (array division): A / small b.
      char A[32];
      int alen = 18;
      build_symbolic_decimal(A, alen, "C4_A", LEAD_NONZERO);
      A[alen] = '\0';
      // Keep divisor to a small single digit to encourage array division fast-path.
      const char *b = "3";
      snprintf(expr, sizeof(expr), "scale=0; %s/%s", A, b);
      break;
    }
    case 5: {
      // C5. Remainder with nonzero requested scale and nonzero modulus.
      // Use concrete numbers known to give nonzero remainder.
      snprintf(expr, sizeof(expr), "scale=3; 12345%%67");
      break;
    }
    case 6: {
      // C6. Division/modulus by zero (error guard).
      int which = klee_range(0, 2, "C6_op"); // 0 -> '/', 1 -> '%'
      if (which == 0) {
        snprintf(expr, sizeof(expr), "98765/0");
      } else {
        snprintf(expr, sizeof(expr), "54321%%0");
      }
      break;
    }
    case 7: {
      // C7. Power with non-integer exponent (error guard).
      snprintf(expr, sizeof(expr), "2^3.5");
      break;
    }
    case 8: {
      // C8. Power with negative, even, multi-bit exponent; include scale to exercise truncation/inversion paths.
      snprintf(expr, sizeof(expr), "scale=5; 7^-10");
      break;
    }
    default: {
      // Fallback: simple expression to remain valid in any case.
      snprintf(expr, sizeof(expr), "1+1");
      break;
    }
  }

  // Prepare argv for bc-style main
  const char *argv2[] = {
    "bc",
    "-e",
    expr,
    NULL
  };

  // Do not touch VM/signals here.
  return real_main(3, argv2);
}