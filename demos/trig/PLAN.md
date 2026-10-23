# Focused KLEE / Gordian demo implementation plan

Implement on `demo/trig-klee-gordian`, with a commit for each feature.

1. Add a reduced teaching example derived from FDLibM's `j0` trigonometric
   guard. Restrict the input to positive binary64 values in [2, 6]. Keep the
   driver separate from the replaceable guard and print branch outcomes only
   during native replay. Link the actual FDLibM sine/cosine implementations
   and their dependency closure into KLEE and native replay; this is not the
   full Bessel function benchmark or the paper's evaluation.
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

Implementation: example, endpoint boundary, focused runner, contract tests,
and presenter guide are authored. See `DEMO.md` at the repository root.
Runtime validation was deferred during the original implementation. The
user subsequently authorized execution; see `DEMO-NOTES.md` for its record.

Follow-up: replaced the initial external-libm simplification with the actual
ten-source FDLibM dependency closure. Each run preserves one source snapshot
for both builds, with hashes, explicit little-endian/aliasing flags, and
namespaced symbols. External math fallback is disabled. Contract tests and
the guide were updated. Execution was subsequently authorized, and a labeled
local mock endpoint was added at the user's request for credential-free rehearsal.
