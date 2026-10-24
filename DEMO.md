# KLEE → Gordian → original-code replay

The current presenter flow uses separate `baseline`, `generate`, and `assisted`
commands plus `python scripts/check_demo.py`. Start with
[DEMO-TUTORIAL.md](DEMO-TUTORIAL.md) for commands, target configuration, and
SUCCESS criteria. The combined five-step invocation documented below remains
available for compatibility.

This demo uses one small example and one OpenAI-compatible model request.
It shows baseline KLEE, its diagnostics, the model's complete response, the
generated code diff, KLEE on that code, and concrete inputs replayed through
the original computation. It does not run the benchmark suite.

**First-time presenter walkthrough:** [DEMO-TUTORIAL.md](DEMO-TUTORIAL.md).

**Rehearsal record and presenter notes:** see [DEMO-NOTES.md](DEMO-NOTES.md)
for the executed checks, results, setup requirements, and a credential-free
rehearsal using an explicitly labeled mock model response. Real provider
credentials and a live model are separate production requirements.

## What the example demonstrates

The source is a teaching reduction of the branch in
`benchmarks/fdlibm_lib/e_j0.c` (`__ieee754_j0`, the Bessel function):

```c
s = sin(x);
c = cos(x);
if (s * c < 0.0) /* outcome 1 */;
else             /* outcome 2 */;
```

The fixed driver restricts a single symbolic binary64 input, `a0`, to
positive values in **[2, 6]**, using integer comparisons on its encoding.
The reduced guard retains the original surrounding bit predicates and
returns 1 or 2 to identify the branch. It removes the Bessel calculations
that do not affect this predicate. The original FDLibM copyright notice is
preserved in `demos/trig/guard.inc`.

**This reduction links the actual FDLibM `sin`/`cos` implementations into
the LLVM bitcode and the native replay executable.** KLEE enters the
functions and their helpers, encountering their masks, shifts, branches,
argument reduction, and polynomial arithmetic. Standard KLEE may concretize
values at symbolic floating-point operations; entering a function does not
mean all its operations remain symbolic. This demonstrates that limitation
and Gordian's surrogate technique. This is a numerical branch, not an actual
malicious logic bomb or a reproduction of the paper's full evaluation.

Each run snapshots these repository files from `benchmarks/fdlibm_lib/`,
plus `fdlibm.h`, into its own `fdlibm/` directory:

| Sources | Purpose |
| --- | --- |
| `s_sin.c`, `s_cos.c` | Public sine and cosine implementations |
| `k_sin.c`, `k_cos.c` | Polynomial kernels |
| `e_rem_pio2.c`, `k_rem_pio2.c` | Argument reduction |
| `s_fabs.c`, `s_floor.c`, `s_scalbn.c`, `s_copysign.c` | Helpers used by the dependency chain |

The baseline, assisted build, and native replay all use the same snapshot.
Its manifest records file hashes and compilation flags. The assisted guard
can avoid calling those functions; they remain linked and unmodified.

Compilation renames the ten FDLibM functions to `gordian_fdlibm_*`, so they
cannot accidentally bind to system libm. The driver declares `sin`/`cos`
directly instead of including system `math.h`, avoiding conflicts between
renaming and system SIMD declarations. `-fno-builtin` prevents compiler math
substitution, `-fno-strict-aliasing` supports FDLibM's historical word macros,
`-D__LITTLE_ENDIAN` selects their correct word order, and
`-ffp-contract=off` prevents fused-operation differences between builds.
The native build does not link `-lm`, and KLEE uses `--external-calls=none`;
an omitted math implementation must fail instead of silently falling back
to a native external call. KLEE intrinsics and its modeled runtime operations
remain available.

An expert's solution is simple:

\[
\sin(x)\cos(x)=\tfrac12\sin(2x).
\]

In the bounded domain, the product is negative on `[2, π)` and `(3π/2, 6]`,
and positive on `(π, 3π/2)`. At the zeros, exact-real reasoning needs
floating-point qualifications. Choose points well inside the intervals:

| Input | Approximate product | Branch |
| --- | --- | --- |
| 2 | −0.3784 | 1, negative |
| 4 | +0.4947 | 2, nonnegative |

Those are analytical examples, **not preloaded demo test cases**. The runner
does not inject these inputs or a prewritten surrogate. It asks the model
to derive an integer-based surrogate, possibly restricted to safe
subintervals, and obtains candidates from KLEE.

## Prepare before the presentation

Use a Linux environment with Docker access, Python 3.10+, the repository,
and a standard KLEE container with clang, LLVM tools, KLEE headers, and
`libkleeRuntest`. Only the standard backend is used; KLEE-Float is unnecessary.

Install the package in a virtual environment from the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

If this workspace mount prohibits virtual-environment symlinks, put the
environment on a Linux filesystem outside the mount. Tested `uv` commands
for that arrangement are in [DEMO-NOTES.md](DEMO-NOTES.md).

The image must **already be available locally**. The demo never downloads,
creates, starts, or recreates a container. If you need to create the
standard container yourself, this preparation command refuses image pulls:

```bash
docker run --pull=never -d --name gordian-klee \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/gordian" -w /gordian \
  klee/klee:3.0 sleep infinity
```

If that container already exists with the correct mount, start it instead:

```bash
docker start gordian-klee
```

The name and mount must match `gordian.yaml`. For a different local image,
substitute its tag in the preparation command and configure the matching
container name. Run from this repository root. Container writes must be
permitted on the mounted directory. Compilation enforces little-endian
IEEE-754 binary64, matching the runner's test decoder.

Choose a model ID offered by your provider. The CLI deliberately has no
default model ID; provider model availability changes.

For OpenRouter, enter your key without putting its value in shell history:

```bash
read -rs -p 'OpenRouter key: ' OPENROUTER_API_KEY
export OPENROUTER_API_KEY
```

The equivalent DeepInfra variable is `DEEPINFRA_API_KEY`. Credentials are
read from the named environment variable, sent only through the SDK, and
excluded from run options and artifacts.

## Run the demo

Use one command, with optional presentation pauses:

```bash
python -m gordian.demo \
  --provider openrouter --model 'YOUR_PROVIDER/MODEL_ID' \
  --name trig-live --pause
```

For DeepInfra:

```bash
python -m gordian.demo \
  --provider deepinfra --model 'YOUR_DEEPINFRA_MODEL_ID' \
  --name trig-deepinfra --pause
```

For any other OpenAI-compatible endpoint:

```bash
read -rs -p 'Endpoint key: ' MY_DEMO_KEY
export MY_DEMO_KEY
python -m gordian.demo \
  --provider custom --base-url 'https://your-service.example/v1' \
  --key-env MY_DEMO_KEY --model 'YOUR_MODEL_ID' \
  --name trig-custom --pause
```

Use the API **base URL**, not its `/chat/completions` URL. DeepInfra's
built-in base is `https://api.deepinfra.com/v1/openai`; OpenRouter's is
`https://openrouter.ai/api/v1`. `--base-url` and `--key-env` can override
either provider's defaults. No authentication values belong in the URL.

To run just the baseline, without a key or model:

```bash
python -m gordian.demo --baseline-only --name trig-baseline
```

Every name must be new; the runner refuses to overwrite an earlier run.
A later full invocation performs a fresh baseline; it does not resume the
baseline-only run. Omit `--pause` for unattended rehearsal.

For a local mock-model rehearsal, start `python demos/trig/mock_endpoint.py`
in another terminal and use `--provider custom`,
`--base-url http://127.0.0.1:8047/v1`, `--model rehearsal-mock`, and a named
environment variable containing a dummy key. Full commands are in the note
sheet. The prewritten response is labeled MOCK throughout; compilation,
KLEE input generation, and original FDLibM replay still execute normally.

## Presenter script

1. **Read the guard.** Ask the audience for inputs producing both signs.
   Explain the human identity and the distinction between mathematical
   functions and the operations supported by the execution engine.
2. **Run baseline KLEE.** Show the printed FDLibM source list,
   concretization diagnostics, and concrete original-code replay observations. Identify
   which outcome is missing. A crash or build failure is not a successful
   demonstration of solver difficulty.
3. **Show the model request.** Open `llm/prompt.md`. The fixed input domain,
   missing outcomes, original guard, and KLEE diagnostics are the evidence
   provided to the model. This focused runner targets a known fragment;
   it skips general LLM triage, partitioning, and inversion to save time.
4. **Read the response and diff.** The full public model response is printed
   when the request completes, followed by its notes and a unified diff.
   Discuss the integer bit comparisons and any restricted safe intervals.
   The driver and input interface remain fixed; only `guard.inc` changes
   for the assisted KLEE build. The runner does not stream private model
   reasoning or token-by-token output.
5. **Watch assisted KLEE and original replay.** KLEE runs the surrogate.
   Each checked candidate is then executed through the separately compiled
   original guard, with the same linked FDLibM implementation. Show the recorded input value,
   raw bytes, branch outcome, and corresponding `.ktest` file.
6. **Read the result.** An `improved` result requires both outcomes across
   the original replay observations, with at least one missing from baseline.
   Explain that these are concrete witnesses, not a proof that the surrogate
   is equivalent over every binary64 input.

The flow uses Gordian's existing bitcode compilation, KLEE runner, test-file
reader/writer, and model file-block protocol. It is a specialized demo entry
point, not the full `gordian run` pipeline. The generated program is an
exploration aid; replay of the fixed original computation decides success.
No assertion softening or surrogate execution is used for final validation.

## Time and success criteria

Defaults are 10 seconds per KLEE invocation, a 2-second solver timeout,
a 60-second SDK request timeout with no automatic retries, and at most
32 native replays per invocation with a 2-second per-test timeout. Both
KLEE runs use the same settings. Override these using `--klee-seconds`,
`--solver-seconds`, `--request-seconds`, `--max-tests`, and `--replay-seconds`.

These are component limits, **not a hard total deadline**: compilation,
tool discovery, KLEE shutdown grace, network behavior, and presentation
pauses add time. Start with a few minutes allocated and measure a rehearsal.
There is one model request and no automatic model-repair loop. A provider
may reject a request, take too long, or return unsuitable code.

| Result | Meaning |
| --- | --- |
| `improved` | Original replay covers both outcomes; baseline missed at least one. |
| `baseline_already_succeeds` | Baseline covers both; the LLM is skipped. No improvement claim. |
| `incomplete` | The checked candidate inputs do not establish both outcomes. Exit code 1. |
| `baseline_only` | Baseline-only run completed; inspect its witnesses. |
| `error` | A prerequisite, build, endpoint, response contract, or execution step failed. Exit code 1. |
| `interrupted` | The presenter interrupted a running demo. Exit code 130. |

The replay cap is printed and recorded. Unchecked tests are retained, but
cannot count as evidence. Reachability is observed per branch using native
output, not inferred from line coverage or the model's claims.

## Artifacts to keep open

```text
runs/trig-live/
  result.json                 settings, status, timings, usage, witnesses
  original/driver.c            fixed input/replay driver
  original/guard.inc           original reduced guard
  fdlibm/*.c                  ten original FDLibM implementation/helper files
  fdlibm/fdlibm.h              original FDLibM header
  fdlibm/manifest.json         exact source hashes and shared compilation flags
  native/original-replay      native executable of that original computation
  native/build.log
  baseline/klee.klee.log       actual KLEE command and captured output
  baseline/klee.warnings.txt
  baseline/klee/*.ktest
  baseline/replay/             per-test logs and observations.json
  llm/prompt.md
  llm/response.md
  surrogate/guard.inc          model-generated replacement
  surrogate/notes.md
  surrogate.patch
  assisted/klee.klee.log
  assisted/klee/*.ktest
  assisted/replay/             original-code observations for assisted tests
```

No final cleanup removes these artifacts. The native executable always
uses the original guard and FDLibM snapshots, including for assisted candidates.

## Rehearsal and troubleshooting

Run the focused contract tests when execution is allowed:

```bash
pytest -q tests/test_trig_demo.py
```

They use fake endpoint/container boundaries and do not require Docker or
provider access. They check input/replay contracts, response parsing, API
configuration, artifact visibility, success accounting, and error retention.
They also check FDLibM source preservation, consistent compile/link inputs,
symbol renaming, and the absence of external math fallback.
They do not replace an actual KLEE/model rehearsal.

- **Container rejected:** check its name, running state, mount, and tools.
  The demo intentionally does not invoke Gordian's automatic container setup.
- **401/403/404 or request timeout:** check your key variable, base URL,
  model ID, access, and network connectivity. Provider error bodies are not
  echoed because they can contain sensitive data.
- **No tests/build failure:** inspect `build/build.log` and `klee.klee.log`
  under the failing variant. Do not describe a broken setup as a solver failure.
- **Malformed response or compilation failure:** inspect `llm/response.md`
  and the generated diff. Try a suitable coding model in a fresh run. The demo
  does not silently substitute a canned solution. The separate, explicit
  mock endpoint is only a rehearsal fixture.
- **`incomplete`:** inspect actual original replay logs and model restrictions.
  Invalid interfaces, failed replays, and inputs outside [2, 6] are rejected.
- **Baseline succeeds:** retain that result honestly. Rehearse on the intended
  backend; do not manufacture a missed branch or describe this run as improvement.
  Linked FDLibM introduces internal integer branches that may help KLEE find
  both sign outcomes even if a version with external trigonometric calls did not.

For a short talk, prepare a recording of an actual successful rehearsal and
keep its artifacts. If the live endpoint fails, show that recording and label
it as recorded. The runner has no fake-success mode; using the local mock
endpoint does not bypass KLEE or original-code replay.
If you edit model code by hand, label the run as a manual intervention.
