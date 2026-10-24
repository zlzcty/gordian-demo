# Model Notes

## Floating point comparison surrogate
- Original lines: 13-13
- Replaced fragment: Floating point comparison (a - b == 0)
- Surrogate: Branched on the integer bit pattern of the float representation, using `uint64_t` and `klee_choose`. Assumed `a` to be in the range [0, 100) with a step of 70 to preserve the original functionality.
