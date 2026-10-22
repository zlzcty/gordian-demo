#include "klee_extra.h"
#include <klee/klee.h>
#include "jv.h"

int main(int argc, char **argv) {
    int klass = klee_range(1, 9, "klass");

    char input[255];
    klee_make_symbolic(input, sizeof(input), "json_input");
    // Ensure null termination
    input[254] = '\0';

    jv parsed;
    jv key, value, slice_key, del_key;
    jv keys_array, target, replacement;
    int idx;

    switch (klass) {
        case 1: // C1: Slice object with missing start/end fields
            // Build: {"slice": {"start": 1}}  (missing "end")
            // Or: {"slice": {"end": 2}} (missing "start")
            // We'll pick one variant
            // Let's do: { "slice": { "start": 1 } }
            // We'll concretize structure, keep numbers symbolic if possible, but here we need concrete 1.
            // Actually, the branch depends on missing field, so we can fix shape.
            // We'll make symbolic choice for which field is missing.
            int missing_field = klee_range(0, 2, "missing_field"); // 0=missing end, 1=missing start
            if (missing_field == 0) {
                // { "slice": { "start": 1 } }
                const char* cinput = "{\"slice\": {\"start\": 1}}";
                memcpy(input, cinput, strlen(cinput) + 1);
            } else {
                // { "slice": { "end": 2 } }
                const char* cinput = "{\"slice\": {\"end\": 2}}";
                memcpy(input, cinput, strlen(cinput) + 1);
            }
            parsed = jv_parse(input);
            // Now we need to call something that uses this slice object, e.g., jv_get(parsed, slice_key)
            // But slice_key must be a slice object. We can construct it from parsed["slice"].
            if (jv_is_valid(parsed)) {
                jv slice_obj = jv_object_get(jv_copy(parsed), jv_string("slice"));
                // Now try jv_get on an array/string target with this slice_obj as key
                jv arr_target = jv_array(); // empty array
                jv_get(arr_target, slice_obj); // should trigger slice parsing with missing field
                jv_free(slice_obj);
                jv_free(arr_target);
                jv_free(parsed);
            }
            break;

        case 2: // C2: Non-array/string target with slice object
            // Target is number, key is slice object
            parsed = jv_parse("123"); // number target
            if (jv_is_valid(parsed)) {
                // build a slice object key: {"start":0, "end":1}
                jv start = jv_number(0);
                jv end = jv_number(1);
                slice_key = jv_object();
                jv_object_set(&slice_key, jv_string("start"), start);
                jv_object_set(&slice_key, jv_string("end"), end);
                jv_get(jv_copy(parsed), slice_key); // should trigger error path
                jv_free(parsed);
            }
            break;

        case 3: // C3: Array slice assignment with size mismatch
            // parsed = [10,20,30]
            // slice = 1:2
            // replacement = [99]  (len 1 vs slice len 1, but if we do 0:2, len 2 vs replacement len 1)
            // Let's do: target length 3, slice 0:2 (length 2), replacement length 1
            parsed = jv_parse("[10,20,30]");
            if (jv_is_valid(parsed)) {
                // slice key: {start:0, end:2}
                jv start = jv_number(0);
                jv end = jv_number(2);
                slice_key = jv_object();
                jv_object_set(&slice_key, jv_string("start"), start);
                jv_object_set(&slice_key, jv_string("end"), end);
                replacement = jv_parse("[99]");
                jv_set(parsed, slice_key, replacement); // mismatch: shrink array
                // jv_free done by jv_set? We assume it consumes.
            }
            break;

        case 4: // C4: Negative and slice deletion keys
            // keys_array = [-1, {"start":0,"end":1}]
            parsed = jv_parse("[1,2,3,4,5]"); // target array
            keys_array = jv_array();
            jv_array_append(&keys_array, jv_number(-1)); // negative index
            // slice object
            slice_key = jv_object();
            jv_object_set(&slice_key, jv_string("start"), jv_number(0));
            jv_object_set(&slice_key, jv_string("end"), jv_number(1));
            jv_array_append(&keys_array, slice_key);
            jv_dels(parsed, keys_array); // mixed keys
            break;

        case 5: // C5: NaN index handling
            // key = NaN
            parsed = jv_parse("[1,2,3]");
            key = jv_nan();
            jv_get(jv_copy(parsed), key);
            jv_free(key);
            jv_free(parsed);
            break;

        case 6: // C6: Invalid slice object structure
            // slice = {start: "abc", end: 2}
            parsed = jv_parse("[1,2,3]");
            slice_key = jv_object();
            jv_object_set(&slice_key, jv_string("start"), jv_string("abc")); // non-numeric
            jv_object_set(&slice_key, jv_string("end"), jv_number(2));
            jv_get(jv_copy(parsed), slice_key);
            jv_free(parsed);
            break;

        case 7: // C7: Extreme numeric indices
            // key = INT_MAX or INT_MIN
            parsed = jv_parse("[1,2,3]");
            int extreme = klee_range(0, 2, "extreme");
            if (extreme == 0)
                key = jv_number(2147483647); // INT_MAX
            else
                key = jv_number(-2147483648); // INT_MIN
            jv_get(jv_copy(parsed), key);
            jv_free(key);
            jv_free(parsed);
            break;

        case 8: // C8: Mixed valid/invalid slice operations
            // keys_array = [{"start":0,"end":1}, {"start":"a","end":1}]
            parsed = jv_parse("[1,2,3]");
            keys_array = jv_array();
            // valid slice
            slice_key = jv_object();
            jv_object_set(&slice_key, jv_string("start"), jv_number(0));
            jv_object_set(&slice_key, jv_string("end"), jv_number(1));
            jv_array_append(&keys_array, jv_copy(slice_key));
            jv_free(slice_key);
            // invalid slice
            slice_key = jv_object();
            jv_object_set(&slice_key, jv_string("start"), jv_string("a")); // invalid
            jv_object_set(&slice_key, jv_string("end"), jv_number(1));
            jv_array_append(&keys_array, slice_key);
            jv_dels(parsed, keys_array);
            break;

        default:
            klee_assert(0);
    }

    return 0;
}