"""Prompt / task text for the three kinds of ghost code plus the
difficult-fragment triage prompt.  Every task is phrased for an agent (it may
read files and run experiments) and degrades gracefully to a single API call
(the file contents are inlined by ``Backend.render_task_prompt``).
"""
from __future__ import annotations

KLEE_RULES = """\
KLEE rules (both KLEE 3.0 and KLEE-Float accept these):
- Symbolic inputs: klee_make_symbolic(&v, sizeof(v), "name"); constraints: klee_assume(cond);
  ranges: klee_range(lo, hi, "name") (hi exclusive); klee_assert(cond); klee_silent_exit(0).
- Only #include <klee/klee.h> is needed for the intrinsics. "klee_extra.h" (same include path) provides
  klee_choose(name, lo, hi), an inclusive-range symbolic int.
- Plain C99, no C++, no VLAs with symbolic size, no threads, no printf of symbolic data needed.
- Every symbolic object must have a distinct name; keep names short and stable.
- Declare main as `int main(int argc, char **argv)` (KLEE's POSIX runtime requires the arguments).
- klee_make_symbolic(p, n, name): p must point to a real, writable object of EXACTLY n bytes
  (`klee_make_symbolic(&x, sizeof x, "x")`, `klee_make_symbolic(buf, sizeof buf, "buf")` for arrays);
  never pass sizeof a pointer, a string literal, a NULL/uninitialised pointer or a size larger than the object:
  KLEE aborts the path with "Wrong size given to klee_make_symbolic" / "invalid pointer: make_symbolic".
  The pointer must be the START of a complete object and n its full size: you cannot make a single element,
  a sub-range (`buf + i`) or a struct field symbolic on its own.  Make the whole buffer/struct symbolic once,
  then shape it with klee_assume on the elements (`klee_assume(buf[i] >= 'a' && buf[i] <= 'z')`) or copy
  symbolic values into place.
- Heap objects for topologies: malloc them first, then make their fields symbolic; keep counts small.
"""

PARTITION_TASK = """\
You are extending KLEE symbolic execution with *semantic heap/input partitioning* (ghost code).
The program under test could not be covered by plain KLEE in the lines marked `// UNCOVERED`.
KLEE explodes on the number of possible heap shapes / input structures; instead of exploring all of
them we constrain the input to a small number of *semantic topologies*: partially concrete, partially
symbolic configurations that are meaningful in this program's domain (e.g. for a parser: a document
with directives, a flow mapping, an anchor+alias pair, an unterminated quoted scalar...; for a data
structure: a chain, a ring, a tree with a shared subtree...).  Concrete structure, symbolic values.

Entry function driven by the harness: `{entry}`
Target notes: {notes}

Write {k} harness variants, `{prefix}1.c` ... `{prefix}{k}.c`.  Each variant is a complete C file
with its own `int main(void)` (plus static helpers) that:
  1. declares a fresh symbolic selector  `int klass = klee_range(0, N, "klass");` (N = number of cases,
     between 4 and 10) and a `switch (klass)` where each case builds ONE semantic topology:
     fixed structure / skeleton, symbolic contents (`klee_make_symbolic` on the value fields, bounded by
     `klee_assume` to the alphabet the code expects);
  2. then calls the entry function exactly as the original harness does (same setup / teardown);
  3. targets the UNCOVERED lines: read them, understand which input structures reach them, and make
     the cases of the {k} variants complementary (variant 1 = most common structures, later variants =
     progressively rarer / deeper paths, error paths, boundary sizes);
  4. keeps symbolic buffers small (<= the original harness sizes) so KLEE finishes paths.
The library / program sources are NOT to be modified: only the harness changes.
Do not include the original harness's `main` twice.  Compile-check with the include flags given below
if you can run a shell (an error-free `clang -fsyntax-only` is enough).

Compile flags used: {cflags}
{klee_rules}
"""

PARTITION_SINGLE_FILE_TASK = """\
You are extending KLEE symbolic execution with *semantic partitioning* (ghost code).
The program `{program}` contains its own KLEE `main()` which makes the inputs symbolic and calls the
code under test, but KLEE could not reach the lines marked `// UNCOVERED` (path explosion on
pointer/heap shapes, dispatch tables, loops over structured input, ...).

Write {k} replacement harness files `{prefix}1.c` ... `{prefix}{k}.c`.  Each is a C file that contains
ONLY a new `int main(void)` (plus static helpers and `#include` lines; it must NOT redefine any
function or global of the program, which is linked in separately with its original main renamed).
Declare the program's functions you call with `extern` prototypes copied from the program.
Each main():
  1. declares a fresh symbolic selector `int klass = klee_range(0, N, "klass");` and a `switch (klass)`
     with 3-8 cases; each case builds ONE semantically meaningful, partially-concrete configuration of
     the inputs/heap (concrete shape and links, symbolic values with `klee_make_symbolic` bounded by
     `klee_assume`), chosen so that the UNCOVERED lines become reachable;
  2. calls the same function(s) the original main calls, with the configured inputs.
The variants must be complementary (different families of configurations).  Keep inputs small.
{klee_rules}
"""

REWRITE_TASK = """\
You are extending KLEE symbolic execution with *surrogate models* (ghost code).
Some fragments of the program are hostile to the SMT solver (non-linear / floating-point arithmetic,
transcendental or crypto/hash functions, bit tricks on IEEE-754 representations, external library or
system calls, printf/scanf/file I/O, inline assembly, threads).  KLEE could not cover the lines
marked `// UNCOVERED` in `{program}`.

Produce `{output}`: a rewritten copy of `{program}` in which ONLY the difficult fragments that block
the UNCOVERED lines are replaced by solver-friendly surrogates, such that
  (1) functionality (outputs, branch outcomes) is preserved for the inputs that matter, or, if full
      generality is impossible, for a subset restricted with `klee_assume`;
  (2) the rewritten code lives in solver-friendly theories: bit-vectors, linear integer arithmetic,
      explicit case splits (`if`/`switch`) instead of symbolic indexing or function pointers,
      small bounded loops; floating-point reasoning should become integer reasoning when the logic
      permits (e.g. `if (pow(x,2) == 49.0)` -> `if (x == 7 || x == -7)`).  IMPORTANT: standard KLEE
      cannot reason about floating-point operations on symbolic values at all: the first FP comparison or
      arithmetic on a symbolic double concretizes it to a single value ("silently concretizing (reason:
      floating point)" in klee_notes.txt) and all later branches see only that value.  Guards must
      therefore be decided on the integer bit pattern of the input (memcpy into uint64_t / the high and
      low 32-bit words), with explicit case splits, and FP arithmetic applied only to concrete values;
  (3) any external library / crypto / system call is replaced by a stub implementation that models
      its effect on control flow (comment what is modelled);
  (4) I/O: scanf/fgets/file reads become symbolic inputs, printf is removed unless it affects state;
  (5) the symbolic INPUT INTERFACE IS UNCHANGED: the same `klee_make_symbolic` objects with the same
      names and sizes, in the same order (test cases generated on the surrogate are replayed on the
      ORIGINAL program; that is how coverage is validated, so any change of names/sizes makes the
      tests useless).  Keep `main()` as it is unless it contains the difficult fragment.
Everything else is copied verbatim.  Do not delete functions.  Keep all `#include`s needed to compile.
{extra}
{klee_rules}
Also write `{notes_file}`: a short markdown note listing each replaced fragment (original lines,
what it was, what the surrogate assumes).
"""

FDLIBM_HILO_EXTRA = """\
This file is from FDLibM.  The macros __HI(x)/__LO(x)/__HIp(p)/__LOp(p) read or write the high/low
32-bit words of a double through pointer casts.  Keep that behaviour but prefer the memcpy-based
helpers fdlibm_hi/fdlibm_lo/fdlibm_set_hi/fdlibm_set_lo from the local fdlibm.h (macros
__HI_model/__LO_model/__SET_HI_model/__SET_LO_model) which KLEE handles well; a write such as
`__HI(x) = v;` becomes `__SET_HI_model(x, v);` and a read-modify-write goes through a temporary.
Standard KLEE concretizes a symbolic double at its first floating-point comparison or operation, so
the surrogate must express the guards that select the uncovered regions (e.g. `ix >= 0x40000000`,
sign checks, `|x| < 2^-27`) purely on the 32-bit words obtained with the model accessors, and split the
remaining computation into a small number of concrete cases (`klee_range` over representative
values of the word, or explicit `if` chains over bit-pattern ranges).  Polynomial evaluations on
concrete values are fine; focus on transcendental calls (sin, cos, exp, log, sqrt, pow ...)
whose results guard UNCOVERED branches: model them with a small bounded case analysis or an
interval/lookup approximation that preserves the branch structure, and comment the approximation.
"""

TRIAGE_TASK = """\
You are triaging code regions that KLEE (symbolic execution with Z3) could not cover.
For each UNCOVERED region below, decide which ghost-code technique could unlock it and estimate the
chance of success.  Techniques:
  - "partition": the region is unreachable because of heap/pointer shapes, structured input,
    dispatch over many cases -> constrain inputs to semantic topologies (harness-level change).
  - "model": the region is guarded by a solver-hostile computation (transcendental/non-linear math,
    crypto/hash, float bit tricks, I/O, external calls, inline asm, threads) that can be replaced by
    a simpler functional surrogate.
  - "inversion": the region is guarded by a condition on the OUTPUT of a localized difficult
    computation `y = f(x)` of a few inputs that can be inverted or numerically searched
    (e.g. sin/cos/pow/log, atoi/atof, modular arithmetic, checksums over short inputs, simple
    hashes of a few bytes). Crypto (AES, SHA-1 of long inputs) and true one-way functions are NOT
    invertible: give them a low score.
  - "none": dead code, defensive error handling that needs OS failures, or unreachable in this harness.
Return ONLY a JSON array, one object per region, ordered by expected payoff (regions early in the
control flow and guarding more uncovered lines first):
[{{"start": <line>, "end": <line>, "technique": "partition|model|inversion|none",
   "score": <0.0-1.0 chance that the technique unlocks it>, "reason": "<one line>",
   "fragment": {{"start": <line>, "end": <line>}}   // the difficult computation itself, for model/inversion
 }}, ...]
"""

INVERSION_TASK = """\
You are extending KLEE symbolic execution with *ghost inversion and bidirectional constraint
propagation*.  In `{program}` the lines marked `// TARGET` (part of the UNCOVERED
region) are guarded by the result of a solver-hostile fragment (lines {frag_start}-{frag_end}):

{fragment}

Treat the fragment C as a state transformer f from the variables it READS (`Rd`) to the variables it
WRITES (`Wr`).  Produce three files:

1. `{ghost}` - a copy of `{program}` where the fragment is replaced by a *havoc*: every variable in
   `Wr` becomes a fresh symbolic value (`klee_make_symbolic(&v, sizeof v, "ghost_<v>")`, with
   `klee_assume` range restrictions only when the original code guarantees them), everything before
   and after is unchanged, and `klee_assert(0)` is NOT added.  Right before the first TARGET line add
   the statement `klee_mark_target();` (declare it as `void klee_mark_target(void);` at the top;
   leave the body undefined, it is provided).  Keep the original symbolic input interface (same
   `klee_make_symbolic` names/sizes).  When KLEE runs this ghost program, test cases that reach the
   mark give us the *suffix* assignment A_suf: values of the havoc variables (and inputs) that satisfy
   the path condition after the fragment.

2. `inverse.py` - a Python 3 script (standard library only) implementing f^-1:
       python3 inverse.py <ktest.json>
   `<ktest.json>` is `{{"objects": {{"<name>": {{"size": n, "hex": "<bytes>"}}, ...}}}}` with every
   symbolic object of the ghost test case (`ghost_<v>` objects hold the Wr values in the C memory
   layout of that type; original inputs hold the pre-state as KLEE chose it for the prefix).
   It must print ONE JSON object to stdout:
       {{"inputs": {{"<original input object name>": {{"hex": "<bytes of the full object>"}}, ...}},
        "tolerance": {{"<name>": <relative tolerance 0..1>}}, "note": "<how it was inverted>"}}
   giving the values of the *original symbolic inputs* (only the ones the fragment reads, byte-exact,
   same size as the object) that make f produce the given Wr values.  If exact inversion is
   impossible, implement a bounded numeric search (golden-section / bisection / grid / brute force over
   small domains) for the input that brings f's output closest to the requested values, and say so in
   "note"; set "tolerance" to how far KLEE may move each input (relative) while still being likely to
   reach the target (use 0.0 for exact discrete inversions, 0.05-0.5 for approximations).
   Do NOT reason about the prefix/suffix branches: that is the solver's job.  Use the program's own
   arithmetic (reimplement f faithfully in Python, e.g. with struct/math) to verify your answer
   before printing it.

3. `forward.py` - `python3 forward.py <inputs.json>` running the fragment f on its own: the original
   computation reproduced as faithfully as possible (same operations, types, widths and rounding;
   call the same libm functions), NOT a simplification.  Reads the same `inputs` object shape, prints
   `{{"wr": {{"<v>": <number or hex>}}}}`.  It is the forward step of the propagation loop.

Keep all three deterministic and fast (< 2 s per call).
{klee_rules}
"""

SLICE_NOTE = """
Note: the annotated program shows only part of the file (the regions relevant to the target and their
context); every `/* ... lines a-b omitted ... */` marker stands for unchanged original code.  This is
NOT a reason to refuse or to write a placeholder: when you produce a copy of the program, write the
parts you see and keep every marker verbatim where it is -- each marker is expanded back to the
original lines afterwards, so the result is a complete file.
"""

INVERSION_BOMB_HINT = """\
Hint: the program is a LogicBombs benchmark: the TARGET is the `klee_assert(0)` / BOMB_ENDING branch.
"""
