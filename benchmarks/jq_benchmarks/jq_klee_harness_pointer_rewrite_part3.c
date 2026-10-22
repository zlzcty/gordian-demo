#include "klee_extra.h"
#include <klee/klee.h>
#include "jv.h"
#include <string.h>

// Helper to create minimal JSON arrays with specific structures
void build_json_array(char* buffer, int size, int case_type, int has_duplicates) {
    int pos = 0;
    
    // Start array
    buffer[pos++] = '[';
    
    if (size > 0) {
        // First element
        buffer[pos++] = '{';
        buffer[pos++] = '"';
        buffer[pos++] = 'k';
        buffer[pos++] = 'e';
        buffer[pos++] = 'y';
        buffer[pos++] = '"';
        buffer[pos++] = ':';
        buffer[pos++] = '"';
        
        // Symbolic key value - keep most of it symbolic but ensure structure
        char key_part[10];
        klee_make_symbolic(key_part, sizeof(key_part), "key_part");
        for (int i = 0; i < 8 && pos < 250; i++) {
            buffer[pos++] = key_part[i];
        }
        
        buffer[pos++] = '"';
        buffer[pos++] = '}';
        
        // Additional elements
        for (int i = 1; i < size; i++) {
            buffer[pos++] = ',';
            buffer[pos++] = '{';
            buffer[pos++] = '"';
            buffer[pos++] = 'k';
            buffer[pos++] = 'e';
            buffer[pos++] = 'y';
            buffer[pos++] = '"';
            buffer[pos++] = ':';
            buffer[pos++] = '"';
            
            // For duplicate case, sometimes reuse the same key structure
            if (has_duplicates && i == size-1) {
                // Force a duplicate by copying the first key pattern
                for (int j = 0; j < 8 && pos < 250; j++) {
                    buffer[pos++] = key_part[j];
                }
            } else {
                // Unique key - use different symbolic content
                char unique_key[10];
                klee_make_symbolic(unique_key, sizeof(unique_key), "unique_key");
                for (int j = 0; j < 8 && pos < 250; j++) {
                    buffer[pos++] = unique_key[j];
                }
            }
            
            buffer[pos++] = '"';
            buffer[pos++] = '}';
        }
    }
    
    buffer[pos++] = ']';
    buffer[pos] = '\0';
}

int main(int argc, char **argv) {
    int klass = klee_range(1, 5, "klass");
    
    char input[512];
    memset(input, 0, sizeof(input));
    
    switch(klass) {
        case 1:  // C1: Empty input arrays
            strcpy(input, "[]");
            break;
            
        case 2:  // C2: Single-element arrays  
            build_json_array(input, 1, 2, 0);
            break;
            
        case 3:  // C3: Multi-element arrays with duplicate keys
            build_json_array(input, 3, 3, 1);  // Force duplicates
            break;
            
        case 4:  // C4: Multi-element arrays with all unique keys
            build_json_array(input, 3, 4, 0);  // All unique
            break;
            
        default:
            // Fallback - symbolic input
            klee_make_symbolic(input, sizeof(input) - 1, "json_input");
            input[sizeof(input) - 1] = '\0';
            break;
    }
    
    jv v = jv_parse(input);
    
    if (jv_is_valid(v)) {
        jv_free(v);
    }
    
    return 0;
}