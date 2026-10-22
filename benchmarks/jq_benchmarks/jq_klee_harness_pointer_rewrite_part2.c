#include "klee_extra.h"
#include <klee/klee.h>
#include "jv.h"

// Helper to create minimal JSON structures for testing
static jv create_minimal_json_object() {
    jv obj = jv_object();
    jv key = jv_string("test");
    jv value = jv_number(42);
    obj = jv_object_set(obj, key, value);
    return obj;
}

static jv create_minimal_json_array() {
    jv arr = jv_array();
    arr = jv_array_append(arr, jv_number(1));
    return arr;
}

int main(int argc, char **argv) {
    int klass = klee_range(1, 9, "klass");
    
    switch(klass) {
        case 1: { // Non-array deletion keys on objects
            // Create invalid path with non-string key
            jv obj = create_minimal_json_object();
            jv invalid_path = jv_array();
            invalid_path = jv_array_append(invalid_path, jv_number(123)); // Non-string key
            
            jv result = jv_delpaths(obj, invalid_path);
            jv_free(result);
            break;
        }
        
        case 2: { // Empty path array edge cases
            jv obj = create_minimal_json_object();
            jv empty_path = jv_array(); // Zero-length path
            
            // Test all path operations with empty path
            jv get_result = jv_getpath(obj, empty_path);
            jv set_result = jv_setpath(obj, empty_path, jv_number(999));
            jv del_result = jv_delpaths(obj, empty_path);
            
            jv_free(get_result);
            jv_free(set_result);
            jv_free(del_result);
            break;
        }
        
        case 3: { // Invalid root object with non-empty paths
            jv invalid_root = jv_invalid(); // Error state root
            jv path = jv_array();
            path = jv_array_append(path, jv_string("key"));
            
            jv get_result = jv_getpath(invalid_root, path);
            jv set_result = jv_setpath(invalid_root, path, jv_number(1));
            
            jv_free(get_result);
            jv_free(set_result);
            break;
        }
        
        case 4: { // Object deletion with nested path specifications
            jv obj = create_minimal_json_object();
            jv nested_path = jv_array();
            nested_path = jv_array_append(nested_path, jv_string("existing"));
            nested_path = jv_array_append(nested_path, jv_string("nonexistent"));
            
            jv result = jv_delpaths(obj, nested_path);
            jv_free(result);
            break;
        }
        
        case 5: { // Array sorting with NaN/number comparisons
            jv arr = jv_array();
            // Add numbers including potential NaN
            arr = jv_array_append(arr, jv_number(1));
            arr = jv_array_append(arr, jv_number(0.0/0.0)); // NaN
            arr = jv_array_append(arr, jv_number(2));
            
            jv sorted = jv_sort(arr, jv_null());
            jv_free(sorted);
            break;
        }
        
        case 6: { // Complex object key comparison scenarios
            jv obj1 = create_minimal_json_object();
            jv obj2 = create_minimal_json_object();
            
            // Compare objects with same structure
            int cmp_result = jv_contains(obj1, obj2);
            klee_assert(cmp_result == 0 || cmp_result == 1);
            
            jv_free(obj1);
            jv_free(obj2);
            break;
        }
        
        case 7: { // Grouping operations with duplicate keys
            jv arr = jv_array();
            // Create objects with duplicate keys for grouping
            jv obj1 = jv_object();
            obj1 = jv_object_set(obj1, jv_string("group"), jv_number(1));
            
            jv obj2 = jv_object();
            obj2 = jv_object_set(obj2, jv_string("group"), jv_number(1)); // Duplicate key
            
            arr = jv_array_append(arr, obj1);
            arr = jv_array_append(arr, obj2);
            
            jv grouped = jv_group(arr, jv_string("group"));
            jv_free(grouped);
            break;
        }
        
        case 8: { // Path operations with object-typed path elements
            jv obj = create_minimal_json_object();
            jv complex_path = jv_array();
            complex_path = jv_array_append(complex_path, create_minimal_json_object()); // Object as path
            
            jv result = jv_setpath(obj, complex_path, jv_number(123));
            jv_free(result);
            break;
        }
    }
    
    return 0;
}