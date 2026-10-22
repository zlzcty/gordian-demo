# Focused KLEE / Gordian demo implementation plan

Implement on `demo/trig-klee-gordian`, with a commit for each feature.

1. Add a reduced teaching example derived from FDLibM's `j0` trigonometric
   guard. Restrict the input to positive binary64 values in [2, 6]. Keep the
   driver separate from the replaceable guard and print branch outcomes only
   during native replay. External libm is intentional; this is not the full
   FDLibM benchmark or the paper's evaluation.
2. Add a small OpenAI-compatible endpoint adapter using Gordian's existing
   backend, prompt/file protocol, and response logs. Endpoint, model, key
   environment variable, timeout, and retries must be explicit arguments.
3. Add a focused runner: baseline KLEE, diagnostics, one model request,
   original/generated diff, assisted KLEE, and independent native replay of
   each candidate through the original guard. Require witnesses for both
   outcomes. Preserve artifacts and report baseline-already-succeeds and
   failure outcomes honestly. Never create containers or pull images.
4. Add focused tests and a presenter guide covering preparation, commands,
   expected evidence, limits, troubleshooting, and a recorded fallback.

Architecture: pure transformation and reporting functions, separate endpoint
and execution boundaries, explicit dependencies and paths, no new classes.
Use the existing backend/container objects only at those boundaries.

Validation constraint: the user has prohibited builds, benchmark execution,
model calls, and container pulls during implementation. Author tests and
review source/diffs, but do not execute tests or the demo. Document this
limitation rather than claiming a successful rehearsal.
