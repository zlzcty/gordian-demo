#include "klee_extra.h"
#include <klee/klee.h>
#include "jv.h"

// Helper function to create symbolic JSON strings with specific structure
char* create_json_string(int size, const char* prefix, const char* suffix) {
    char* str = malloc(size);
    klee_make_symbolic(str, size, "json_string");
    
    // Copy prefix
    int prefix_len = strlen(prefix);
    memcpy(str, prefix, prefix_len);
    
    // Ensure suffix is at the end
    int suffix_len = strlen(suffix);
    memcpy(str + size - suffix_len - 1, suffix, suffix_len);
    str[size - 1] = '\0';  // Ensure null termination
    
    return str;
}

// Helper to create a JSON string with hash colliding keys
char* create_colliding_keys_json(int size) {
    // Create a JSON object with keys that are likely to collide in hash function
    char* str = malloc(size);
    
    // Start with object opening
    strcpy(str, "{");
    
    // Add some keys that might collide (using similar structures)
    char* middle = str + 1;
    klee_make_symbolic(middle, size - 10, "json_middle");
    
    // Ensure we have multiple key-value pairs
    int pos = 1;
    for (int i = 0; i < 3 && pos < size - 20; i++) {
        // Insert key-value pairs that might have hash collisions
        pos += sprintf(str + pos, "\"k%d\":\"v%d\",", i, i);
    }
    
    // Close the JSON object properly
    strcpy(str + strlen(str) - 1, "}");
    str[size - 1] = '\0';
    
    return str;
}

int main(int argc, char **argv) {
    // Create a symbolic variable to choose between different test cases
    int klass = klee_range(1, 9, "klass");
    
    // Common variables used across cases
    char* json_input;
    jv parsed;
    jv obj1, obj2, result;
    
    switch (klass) {
        case 1: {
            // C1: Empty Object Operations
            // Create an empty JSON object "{}" to test empty object operations
            json_input = strdup("{}");
            parsed = jv_parse(json_input);
            
            // Perform operations on the empty object to trigger uncovered code
            if (jv_is_valid(parsed)) {
                // Try to access a non-existent key to trigger jvp_object_find_slot
                jv key = jv_string("non_existent_key");
                jv value = jv_object_get(parsed, key);
                
                // Try iteration on empty object
                int iter = jv_object_iter(parsed);
                if (iter) {
                    jv_object_iter_next(parsed, iter);
                }
                
                jv_free(key);
                jv_free(value);
                jv_free(parsed);
            }
            free(json_input);
            break;
        }
        
        case 2: {
            // C2: Object Hash Collisions
            // Create JSON with potential hash collisions
            json_input = create_colliding_keys_json(100);
            parsed = jv_parse(json_input);
            
            if (jv_is_valid(parsed)) {
                // Try operations that would traverse collision chains
                jv key = jv_string("k1");
                jv value = jv_object_get(parsed, key);
                
                // Try to delete a key to exercise deletion with collisions
                jv removed = jv_object_delete(parsed, key);
                
                jv_free(key);
                jv_free(value);
                jv_free(removed);
                jv_free(parsed);
            }
            free(json_input);
            break;
        }
        
        case 3: {
            // C3: Object Capacity Expansion
            // Create a JSON object with many key-value pairs to force capacity expansion
            json_input = create_json_string(255, "{\"", "\"}");
            
            // Insert many key-value pairs to force rehashing
            parsed = jv_parse(json_input);
            
            if (jv_is_valid(parsed)) {
                // Start with a small object
                obj1 = jv_object();
                
                // Add many keys to trigger capacity expansion and rehashing
                for (int i = 0; i < 20; i++) {
                    char key_buf[10];
                    sprintf(key_buf, "key%d", i);
                    jv key = jv_string(key_buf);
                    jv val = jv_number(i);
                    obj1 = jv_object_set(obj1, key, val);
                }
                
                jv_free(obj1);
                jv_free(parsed);
            }
            free(json_input);
            break;
        }
        
        case 4: {
            // C4: Shared Object Modification
            // Create a simple object
            json_input = strdup("{\"key\":\"value\"}");
            parsed = jv_parse(json_input);
            
            if (jv_is_valid(parsed)) {
                // Create a shared object by copying
                obj1 = parsed;
                obj2 = jv_copy(obj1);  // Now obj1 and obj2 share the same internal object
                
                // Modify the shared object to trigger unsharing
                jv key = jv_string("new_key");
                jv value = jv_string("new_value");
                obj1 = jv_object_set(obj1, key, value);  // This should trigger unsharing
                
                jv_free(obj1);
                jv_free(obj2);
            }
            free(json_input);
            break;
        }
        
        case 5: {
            // C5: Object Equality Comparison
            // Create two objects to compare
            char* json1 = strdup("{\"a\":1,\"b\":2}");
            char* json2 = strdup("{\"b\":2,\"a\":1}");  // Same content, different order
            
            obj1 = jv_parse(json1);
            obj2 = jv_parse(json2);
            
            if (jv_is_valid(obj1) && jv_is_valid(obj2)) {
                // Compare objects for equality to trigger jvp_object_equal
                int equal = jv_equal(obj1, obj2);
                
                // Also test with nested objects
                jv nested1 = jv_parse("{\"x\":{\"y\":3}}");
                jv nested2 = jv_parse("{\"x\":{\"y\":3}}");
                if (jv_is_valid(nested1) && jv_is_valid(nested2)) {
                    equal = jv_equal(nested1, nested2);
                    jv_free(nested1);
                    jv_free(nested2);
                }
                
                jv_free(obj1);
                jv_free(obj2);
            }
            free(json1);
            free(json2);
            break;
        }
        
        case 6: {
            // C6: Object Recursive Merging
            // Create two objects with nested structures to merge
            char* json1 = strdup("{\"a\":1,\"b\":{\"x\":1}}");
            char* json2 = strdup("{\"b\":{\"y\":2},\"c\":3}");
            
            obj1 = jv_parse(json1);
            obj2 = jv_parse(json2);
            
            if (jv_is_valid(obj1) && jv_is_valid(obj2)) {
                // Merge the objects recursively
                result = jv_object_merge_recursive(obj1, obj2);
                jv_free(result);
            }
            free(json1);
            free(json2);
            break;
        }
        
        case 7: {
            // C7: Object Key Deletion
            json_input = strdup("{\"key1\":\"value1\",\"key2\":\"value2\",\"key3\":\"value3\"}");
            parsed = jv_parse(json_input);
            
            if (jv_is_valid(parsed)) {
                // Delete keys to trigger jvp_object_delete
                jv key = jv_string("key2");
                result = jv_object_delete(parsed, key);
                
                // Try deleting a non-existent key
                jv nonexistent = jv_string("nonexistent");
                result = jv_object_delete(result, nonexistent);
                
                jv_free(key);
                jv_free(nonexistent);
                jv_free(result);
            }
            free(json_input);
            break;
        }
        
        case 8: {
            // C8: Object Iteration
            json_input = strdup("{\"k1\":\"v1\",\"k2\":\"v2\",\"k3\":\"v3\"}");
            parsed = jv_parse(json_input);
            
            if (jv_is_valid(parsed)) {
                // Iterate through all keys and values
                int iter = jv_object_iter(parsed);
                while (iter) {
                    jv key = jv_object_iter_key(parsed, iter);
                    jv value = jv_object_iter_value(parsed, iter);
                    
                    // Free the key and value
                    jv_free(key);
                    jv_free(value);
                    
                    // Move to next item
                    iter = jv_object_iter_next(parsed, iter);
                }
                
                jv_free(parsed);
            }
            free(json_input);
            break;
        }
        
        default: {
            // Default case - use symbolic input like the original harness
            char input[255];
            klee_make_symbolic(input, sizeof(input), "json_input");
            input[254] = '\0';   // ensure termination
            
            jv v = jv_parse(input);
            
            if (jv_is_valid(v)) {
                jv_free(v);
            }
        }
    }
    
    return 0;
}