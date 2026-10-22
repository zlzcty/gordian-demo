#include "klee_extra.h"
#include <string.h>
#include <klee/klee.h>
#include <unistd.h>

#include "status.h"
#include "vm.h"
#include "bc.h"
#include "dc.h"

// Forward declaration of renamed main
int real_main(int argc, const char* argv[]);

#define EXPR_MAX 64

static void sanitize_bytes(char *buf, int n) {
  for (int i = 0; i < n; i++) {
    unsigned char x = (unsigned char) buf[i];
    buf[i] = (char)(32u + (x % 95u));  // printable ASCII
  }
  buf[n - 1] = '\0';
}

// Helper to create minimal bc expression with continuation
static void create_continued_expr(char *expr, size_t max_len) {
  // Minimal expression with continuation: "1 + \\\n 2"
  const char *base = "1 + \\\n 2";
  size_t len = strlen(base);
  if (len < max_len - 1) {
    strcpy(expr, base);
    // Fill rest with symbolic but ensure null termination
    klee_make_symbolic(expr + len, max_len - len - 1, "expr_rest");
    expr[max_len - 1] = '\0';
  } else {
    klee_make_symbolic(expr, max_len, "expr_full");
    expr[max_len - 1] = '\0';
  }
}

int main(int argc, char **argv) {
  int klass = klee_range(1, 7, "klass");
  
  switch (klass) {
    case 1: { // C1: Interactive TTY mode with environment configuration
      // Force TTY mode by ensuring stdin/stdout/stderr are TTYs
      if (isatty(0) && isatty(1) && isatty(2)) {
        char expr[EXPR_MAX];
        klee_make_symbolic(expr, sizeof(expr), "bc_expr");
        sanitize_bytes(expr, EXPR_MAX);
        
        const char *argv[] = {"bc", NULL}; // No expression, forces interactive
        return real_main(1, argv);
      }
      break;
    }
    
    case 2: { // C2: Math library loading with extra math support
      char expr[EXPR_MAX];
      klee_make_symbolic(expr, sizeof(expr), "bc_expr");
      sanitize_bytes(expr, EXPR_MAX);
      
      const char *argv[] = {"bc", "-l", "-e", expr, NULL};
      return real_main(4, argv);
    }
    
    case 3: { // C3: Multi-file processing with non-empty paths
      // Create symbolic file content
      char file1_content[32], file2_content[32];
      klee_make_symbolic(file1_content, sizeof(file1_content), "file1");
      klee_make_symbolic(file2_content, sizeof(file2_content), "file2");
      sanitize_bytes(file1_content, sizeof(file1_content));
      sanitize_bytes(file2_content, sizeof(file2_content));
      
      // Use file arguments instead of -e expression
      const char *argv[] = {"bc", "file1.bc", "file2.bc", NULL};
      return real_main(3, argv);
    }
    
    case 4: { // C4: Expression processing with continuation lines
      char expr[EXPR_MAX];
      create_continued_expr(expr, EXPR_MAX);
      sanitize_bytes(expr, EXPR_MAX);
      
      const char *argv[] = {"bc", "-e", expr, NULL};
      return real_main(3, argv);
    }
    
    case 5: { // C5: Debug mode cleanup path
      // This case relies on BC_DEBUG being defined at compile time
      // We'll create a minimal expression and let the debug paths trigger
      char expr[EXPR_MAX];
      klee_make_symbolic(expr, sizeof(expr), "bc_expr");
      sanitize_bytes(expr, EXPR_MAX);
      
      const char *argv[] = {"bc", "-e", expr, NULL};
      return real_main(3, argv);
    }
    
    case 6: { // C6: Library loading execution path
      // Force library loading by using include path
      char expr[EXPR_MAX];
      klee_make_symbolic(expr, sizeof(expr), "bc_expr");
      sanitize_bytes(expr, EXPR_MAX);
      
      const char *argv[] = {"bc", "-l", "-e", expr, NULL};
      return real_main(4, argv);
    }
    
    default:
      // Fallback to original harness
      char expr[EXPR_MAX];
      klee_make_symbolic(expr, sizeof(expr), "bc_expr");
      sanitize_bytes(expr, EXPR_MAX);
      
      const char *argv[] = {"bc", "-e", expr, NULL};
      return real_main(3, argv);
  }
  
  // Default fallback if cases fail
  char expr[EXPR_MAX];
  klee_make_symbolic(expr, sizeof(expr), "bc_expr");
  sanitize_bytes(expr, EXPR_MAX);
  
  const char *argv[] = {"bc", "-e", expr, NULL};
  return real_main(3, argv);
}