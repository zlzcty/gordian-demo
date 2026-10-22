#include "klee_extra.h"
#include <string.h>
#include <klee/klee.h>
#include <sys/stat.h>
#include <errno.h>

#include "status.h"
#include "vm.h"
#include "bc.h"
#include "dc.h"

// Forward declaration of renamed main
int real_main(int argc, const char* argv[]);

#define EXPR_MAX 64
#define BUF_SIZE 128

// Helper to create test files with specific content
static void create_test_file(const char* filename, const char* content, size_t len) {
    FILE* f = fopen(filename, "wb");
    if (f) {
        fwrite(content, 1, len, f);
        fclose(f);
    }
}

// Helper to create symbolic buffer with binary data
static void make_symbolic_with_binary(char* buf, size_t size, const char* name) {
    klee_make_symbolic(buf, size, name);
    // Force at least one binary character for C2
    if (size > 0) {
        klee_assume((unsigned char)buf[0] < 32 || (unsigned char)buf[0] >= 127);
    }
}

int main(int argc, char** argv) {
    int klass = klee_range(1, 8, "klass"); // 7 semantic cases
    
    switch (klass) {
        case 1: { // C1: Non-Windows file open failure simulation
            // Force non-Windows path but simulate open failure
            const char* invalid_argv[] = {"bc", "nonexistent_file.bc", NULL};
            return real_main(2, invalid_argv);
        }
        
        case 2: { // C2: Binary data detection in small input
            char expr[EXPR_MAX];
            make_symbolic_with_binary(expr, EXPR_MAX, "bc_expr_binary");
            expr[EXPR_MAX - 1] = '\0';
            
            const char* argv[] = {"bc", "-e", expr, NULL};
            return real_main(3, argv);
        }
        
        case 3: { // C3: Signal-interrupted read with quit status
            // This requires more complex setup - we'll create a scenario
            // where read would be interrupted and VM is in quit state
            char expr[EXPR_MAX];
            klee_make_symbolic(expr, sizeof(expr), "bc_expr_eintr");
            
            // Create a file that will trigger read scenarios
            create_test_file("test_eintr.bc", expr, strlen(expr));
            const char* argv[] = {"bc", "test_eintr.bc", NULL};
            
            return real_main(2, argv);
        }
        
        case 4: { // C4: EOF on stdin with partial buffer
            // Use empty expression to trigger EOF-like behavior
            const char* argv[] = {"bc", "-e", "", NULL};
            return real_main(3, argv);
        }
        
        case 5: { // C5: History-enabled TTY input with binary check
            char expr[EXPR_MAX];
            make_symbolic_with_binary(expr, EXPR_MAX, "bc_expr_tty");
            expr[EXPR_MAX - 1] = '\0';
            
            // Set environment to simulate TTY
            setenv("TERM", "xterm", 1);
            const char* argv[] = {"bc", "-e", expr, NULL};
            return real_main(3, argv);
        }
        
        case 6: { // C6: File read error scenarios
            // Create various problematic file scenarios
            int file_type = klee_range(0, 3, "file_error_type");
            
            switch (file_type) {
                case 0: { // Non-existent file
                    const char* argv[] = {"bc", "/invalid/path/file.bc", NULL};
                    return real_main(2, argv);
                }
                case 1: { // Directory instead of file
                    const char* argv[] = {"bc", "/", NULL}; // Use root as directory
                    return real_main(2, argv);
                }
                default: { // Permission denied
                    const char* argv[] = {"bc", "/etc/shadow", NULL}; // Typically restricted
                    return real_main(2, argv);
                }
            }
        }
        
        case 7: { // C7: Partial file read with binary data
            // Create file with binary content
            char file_content[BUF_SIZE];
            make_symbolic_with_binary(file_content, BUF_SIZE, "file_binary_content");
            file_content[BUF_SIZE - 1] = '\0';
            
            create_test_file("test_binary.bc", file_content, BUF_SIZE);
            const char* argv[] = {"bc", "test_binary.bc", NULL};
            return real_main(2, argv);
        }
        
        default: { // Fallback to original harness
            char expr[EXPR_MAX];
            klee_make_symbolic(expr, sizeof(expr), "bc_expr");
            
            // Original sanitization
            for (int i = 0; i < EXPR_MAX; i++) {
                unsigned char x = (unsigned char) expr[i];
                expr[i] = (char)(32u + (x % 95u));
            }
            expr[EXPR_MAX - 1] = '\0';
            
            const char* argv[] = {"bc", "-e", expr, NULL};
            return real_main(3, argv);
        }
    }
}