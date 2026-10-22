/*
TOY:
*/
#include "sha1.h"
#include "utils.h"
#include "../../assume.h"
#include "a_tester.h"

// {"s":{"length": 4}}
int logic_bomb(char* s) {
    assume_NL_start;
    int symvar = s[0] - 48;
    int plaintext = symvar;
    unsigned cipher[5];
    cipher[0] = 0X902ba3cd;
    cipher[1] = 0Xa1883801;
    cipher[2] = 0X594b6e1b;
    cipher[3] = 0X452790cc;
    cipher[4] = 0X53948fda;

    if(SHA1_COMP(plaintext,cipher)==0){
        return BOMB_ENDING;
    }
    
    else{
        return NORMAL_ENDING;
    }
    assume_NL_stop;
}
