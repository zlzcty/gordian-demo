#include <klee/klee.h>
#include "klee_extra.h"
// Small helpers to build expressions safely into a fixed buffer.
static void append_char(char *buf, int *pos, int cap, char c) {
  if (*pos < cap - 1) {
    buf[*pos] = c;
    (*pos)++;
    buf[*pos] = '\0';
  }
}

static void append_str(char *buf, int *pos, int cap, const char *s) {
  while (*s && *pos < cap - 1) {
    buf[*pos] = *s++;
    (*pos)++;
  }
  buf[*pos] = '\0';
}

static void append_uint(char *buf, int *pos, int cap, unsigned int v) {
  char tmp[16];
  int tpos = 0;
  if (v == 0) {
    append_char(buf, pos, cap, '0');
    return;
  }
  while (v > 0 && tpos < (int)sizeof(tmp)) {
    tmp[tpos++] = (char)('0' + (v % 10u));
    v /= 10u;
  }
  while (tpos-- > 0) {
    append_char(buf, pos, cap, tmp[tpos]);
  }
}

// Forward declaration of the target entrypoint.
extern int real_main(int argc, const char* argv[]);

int main(int argc, char **argv) {
  // We construct specific expressions per semantic case and run either bc or dc.
  // Keep the buffer modest in size so printing lines can overflow for case C8.
  enum { EXPR_CAP = 128 };
  char expr[EXPR_CAP];
  int pos = 0;
  expr[0] = '\0';

  const char *prog = "bc";   // default program
  const char *flag = "-e";   // both bc and dc support -e in this codebase

  // Choose which semantic scenario to exercise.
  int klass = klee_range(1, 11, "klass");

  switch (klass) {
    case 1: {
      // C1. Place/truncate scale: "1.<digs> @ b", with b < scale.
      // Build a number with a small fractional length then place to a smaller scale.
      unsigned int flen = klee_range(1, 6, "place_trunc_flen"); // scale = flen
      unsigned int b = klee_range(0, flen, "place_trunc_b");
      if (b >= flen) b = flen - 1; // ensure strictly less than scale

      append_str(expr, &pos, EXPR_CAP, "1.");
      for (unsigned int i = 0; i < flen; i++) {
        // make simple non-zero fractional digits
        char d = (char)('1' + (i % 9));
        append_char(expr, &pos, EXPR_CAP, d);
      }
      append_str(expr, &pos, EXPR_CAP, " @ ");
      append_uint(expr, &pos, EXPR_CAP, b);
    } break;

    case 2: {
      // C2. Place/extend scale: "1.<digs> @ b", with b > scale.
      unsigned int flen = klee_range(0, 5, "place_extend_flen"); // allow 0 to force extend
      unsigned int extend = klee_range(1, 4, "place_extend_delta");
      unsigned int b = flen + extend; // strictly greater

      append_str(expr, &pos, EXPR_CAP, "1.");
      for (unsigned int i = 0; i < flen; i++) {
        char d = (char)('1' + (i % 9));
        append_char(expr, &pos, EXPR_CAP, d);
      }
      append_str(expr, &pos, EXPR_CAP, " @ ");
      append_uint(expr, &pos, EXPR_CAP, b);
    } break;

    case 3: {
      // C3. Left shift operator: "1 << s" with non-negative s.
      unsigned int s = klee_range(0, 6, "shift_left_s");
      append_str(expr, &pos, EXPR_CAP, "1 << ");
      append_uint(expr, &pos, EXPR_CAP, s);
    } break;

    case 4: {
      // C4. Uppercase digit clamping (non-decimal): ibase=N; <LETTER> with LETTER digit >= base.
      unsigned int base = klee_range(11, 20, "clamp_base");     // non-decimal base
      unsigned int letterVal = klee_range(base, 35, "clamp_letterVal"); // ensure >= base
      char letter = (char)('A' + (letterVal - 10));

      append_str(expr, &pos, EXPR_CAP, "ibase=");
      append_uint(expr, &pos, EXPR_CAP, base);
      append_str(expr, &pos, EXPR_CAP, "; obase=10; ");
      append_char(expr, &pos, EXPR_CAP, letter);
    } break;

    case 5: {
      // C5. Uppercase digits in decimal parsing under clamp.
      // Provide a decimal-looking string containing uppercase letters; the parser's clamp path
      // should force substitution to 9. Keep simple: "123A456".
      append_str(expr, &pos, EXPR_CAP, "ibase=10; 123A456");
    } break;

    case 6: {
      // C6. Base-N parse: integer-only, no radix: ibase=16; A
      unsigned int v = klee_range(10, 15, "no_radix_digit"); // within base
      char digit = (char)('A' + (v - 10));
      append_str(expr, &pos, EXPR_CAP, "ibase=16; obase=10; ");
      append_char(expr, &pos, EXPR_CAP, digit);
    } break;

    case 7: {
      // C7. Base-N parse: fractional with scale growth: ibase=16; 1.F[zeros...]
      unsigned int digs = klee_range(1, 5, "frac_digs");
      append_str(expr, &pos, EXPR_CAP, "ibase=16; obase=10; 1.");
      // First fractional digit non-zero to ensure accumulation
      append_char(expr, &pos, EXPR_CAP, 'F'); // 15 in base 16
      for (unsigned int i = 1; i < digs; i++) {
        // Keep the rest zero to focus on scale extension
        append_char(expr, &pos, EXPR_CAP, '0');
      }
    } break;

    case 8: {
      // C8. Printing with line-length overflow: print a long run of digits.
      // A simple big integer literal should trigger line wrap in bc's printer.
      unsigned int nDigits = klee_range(75, 95, "line_overflow_n");
      append_str(expr, &pos, EXPR_CAP, "obase=10; ");
      for (unsigned int i = 0; i < nDigits; i++) {
        char d = (char)('0' + (i % 10));
        append_char(expr, &pos, EXPR_CAP, d);
      }
    } break;

    case 9: {
      // C9. Digit printing in “char” mode (dc’s P command): switch to dc and emit one char.
      prog = "dc";
      unsigned int ch = klee_range(32, 126, "dc_P_char"); // printable ASCII
      // "<value> P" prints the character.
      append_uint(expr, &pos, EXPR_CAP, ch);
      append_str(expr, &pos, EXPR_CAP, " P");
    } break;

    case 10: {
      // C10. Large-base digit printing with radix delimiter: obase >= 17 and a fractional number.
      unsigned int base = klee_range(17, 36, "large_base");
      append_str(expr, &pos, EXPR_CAP, "obase=");
      append_uint(expr, &pos, EXPR_CAP, base);
      append_str(expr, &pos, EXPR_CAP, "; ");
      // Fractional number to force radix '.' emission
      append_str(expr, &pos, EXPR_CAP, "123.45");
    } break;

    default: {
      // Fallback: simple expression to keep harness robust.
      append_str(expr, &pos, EXPR_CAP, "1+2");
    } break;
  }

  // Prepare argv and invoke the target.
  const char *args[] = { prog, flag, expr, NULL };
  return real_main(3, args);
}