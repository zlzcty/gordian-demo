#include <klee/klee.h>
#include<stdio.h>
#include <stdlib.h>
#include "a_tester.h"

// {"s":{"length": 4}}
int logic_bomb(char* s) {
    int symvar = s[0] - 48; // take first character of input string and convert to integer
    // 48 is just the ASCII value of '0'

    // ISSUE STARTS BELOW: 
    float a = symvar/70.0; // 70.0 is double, so symvar is promoted to double and then divided by 70.0, resulting in a float value
    float b = 0.1; 

    // MAIN ISSUE AT THESE CONDITIONS:
    if(a != 0.1){ // float vs double comparison, a is float and 0.1 is double, so a is promoted to double for the comparison
	// ^ a is widened back to double

        if(a - b == 0) // float vs float comparison, a and b are both floats, so the comparison is done in float precision
            // If a is not equal to 0.1, but a - b is equal to 0, it means that a is very 
            // close to 0.1, but not exactly equal to it due to floating-point precision issues.
            
            return BOMB_ENDING; // if both conditions are true, return BOMB_ENDING
    }

    return NORMAL_ENDING; // if conditions are not met, return NORMAL_ENDING
}

int main(int argc, char** argv) {
    char s[5];
    klee_make_symbolic(&s, sizeof(s), "s"); // make the input string symbolic
    klee_assume(s[4]=='\0'); // assume that the last character of the string is null terminator
    return logic_bomb(s); // call the logic_bomb function with the symbolic input string
}
