#include "klee_extra.h"
#include <string.h>
#include <klee/klee.h>
#include <stdlib.h>
#include <unistd.h>

#include "status.h"
#include "vm.h"
#include "bc.h"
#include "dc.h"

// Forward declaration of renamed main
int real_main(int argc, const char* argv[]);

#define EXPR_MAX 64
#define ENV_VAR_MAX 32

static void sanitize_bytes(char *buf, int n) {
  for (int i = 0; i < n; i++) {
    unsigned char x = (unsigned char) buf[i];
    buf[i] = (char)(32u + (x % 95u));
  }
  buf[n - 1] = '\0';
}

// Helper to set environment variables for specific cases
static void setup_env_var(const char* name, const char* value) {
  setenv(name, value, 1);
}

// Helper to simulate allocation failure
static void* failing_malloc(size_t size) {
  static int fail_count = 0;
  fail_count++;
  return NULL;
}

int main(int argc, char **argv) {
  int klass = klee_range(1, 11, "klass");
  
  switch (klass) {
    case 1: { // Non-numeric environment variable
      char env_val[ENV_VAR_MAX];
      klee_make_symbolic(env_val, sizeof(env_val), "env_val");
      // Ensure it contains non-digit characters
      klee_assume(env_val[0] < '0' || env_val[0] > '9');
      setup_env_var("BC_LINE_LENGTH", env_val);
      
      char expr[EXPR_MAX];
      klee_make_symbolic(expr, sizeof(expr), "bc_expr");
      sanitize_bytes(expr, EXPR_MAX);
      
      const char *argv[] = {"bc", "-e", expr, NULL};
      return real_main(3, argv);
    }
    
    case 2: { // Numeric env var exceeding bounds
      char env_val[ENV_VAR_MAX];
      klee_make_symbolic(env_val, sizeof(env_val), "env_val");
      // Force numeric but with extreme values
      klee_assume(env_val[0] >= '0' && env_val[0] <= '9');
      setup_env_var("BC_LINE_LENGTH", env_val);
      
      char expr[EXPR_MAX];
      klee_make_symbolic(expr, sizeof(expr), "bc_expr");
      sanitize_bytes(expr, EXPR_MAX);
      
      const char *argv[] = {"bc", "-e", expr, NULL};
      return real_main(3, argv);
    }
    
    case 3: // Allocation failure with retry success
    case 4: { // Allocation failure with retry failure
      // These require hooking into bc's allocation functions
      // For now, use symbolic input that might trigger allocations
      char expr[EXPR_MAX];
      klee_make_symbolic(expr, sizeof(expr), "bc_expr");
      sanitize_bytes(expr, EXPR_MAX);
      
      const char *argv[] = {"bc", "-e", expr, NULL};
      return real_main(3, argv);
    }
    
    case 5: { // Size calculation overflow
      // Create expression that might trigger large allocations
      char expr[EXPR_MAX];
      klee_make_symbolic(expr, sizeof(expr), "bc_expr");
      // Force a very long expression to potentially overflow
      for (int i = 0; i < EXPR_MAX - 1; i++) {
        klee_assume(expr[i] != '\0');
      }
      sanitize_bytes(expr, EXPR_MAX);
      
      const char *argv[] = {"bc", "-e", expr, NULL};
      return real_main(3, argv);
    }
    
    case 6: { // Initialized read parser at shutdown
      // Use stdin mode to initialize read parser
      const char *argv[] = {"bc", NULL};
      return real_main(1, argv);
    }
    
    case 7: { // DC program with unsafe results stack
      char dc_expr[EXPR_MAX];
      klee_make_symbolic(dc_expr, sizeof(dc_expr), "dc_expr");
      sanitize_bytes(dc_expr, EXPR_MAX);
      
      const char *argv[] = {"dc", "-e", dc_expr, NULL};
      return real_main(3, argv);
    }
    
    case 8: { // Stdin with continuation backslash
      // This requires actual stdin interaction - use file input instead
      char expr[EXPR_MAX];
      klee_make_symbolic(expr, sizeof(expr), "bc_expr");
      // Include backslash for continuation
      klee_assume(expr[0] == '\\');
      sanitize_bytes(expr, EXPR_MAX);
      
      const char *argv[] = {"bc", "-e", expr, NULL};
      return real_main(3, argv);
    }
    
    case 9: { // File with unclosed if statements
      char expr[EXPR_MAX];
      klee_make_symbolic(expr, sizeof(expr), "bc_expr");
      // Start with if but don't close it properly
      klee_assume(expr[0] == 'i' && expr[1] == 'f');
      sanitize_bytes(expr, EXPR_MAX);
      
      const char *argv[] = {"bc", "-e", expr, NULL};
      return real_main(3, argv);
    }
    
    case 10: { // Non-fatal error recovery
      char expr[EXPR_MAX];
      klee_make_symbolic(expr, sizeof(expr), "bc_expr");
      // Include syntax that causes recoverable errors
      klee_assume(expr[0] == '(' && expr[1] != ')');
      sanitize_bytes(expr, EXPR_MAX);
      
      const char *argv[] = {"bc", "-e", expr, NULL};
      return real_main(3, argv);
    }
    
    default: {
      // Default case similar to original harness
      char expr[EXPR_MAX];
      klee_make_symbolic(expr, sizeof(expr), "bc_expr");
      sanitize_bytes(expr, EXPR_MAX);
      
      const char *argv[] = {"bc", "-e", expr, NULL};
      return real_main(3, argv);
    }
  }
}