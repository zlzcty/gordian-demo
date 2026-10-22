# KLEE → Gordian → original-code replay

This demo uses one small example and one OpenAI-compatible model request.
It shows baseline KLEE, its diagnostics, the model's complete response, the
generated code diff, KLEE on that code, and concrete inputs replayed through
the original computation. It does not run the benchmark suite.

**Implementation status:** authored and statically reviewed only. No demo,
tests, compilation, endpoint request, or container operation was executed
during implementation, as requested. Rehearse before presenting; successful
runtime behavior and duration have not been established.

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

**This reduction calls external system libm `sin`/`cos`. It does not link
the FDLibM implementations of those functions.** Standard KLEE normally
concretizes symbolic floating-point/external-call operands, so it may
explore only one sign outcome. This demonstrates that limitation and
Gordian's surrogate technique; it does not establish that a floating-point
SMT solver cannot solve the full FDLibM example. This is a difficult branch,
not an actual malicious logic bomb or a reproduction of the paper's results.

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

## Presenter script

1. **Read the guard.** Ask the audience for inputs producing both signs.
   Explain the human identity and the distinction between mathematical
   functions and the operations supported by the execution engine.
2. **Run baseline KLEE.** Show the printed concretization/external-call
   warnings and the concrete original-code replay observations. Identify
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
   original guard, with external native libm. Show the recorded input value,
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

The replay cap is printed and recorded. Unchecked tests are retained, but
cannot count as evidence. Reachability is observed per branch using native
output, not inferred from line coverage or the model's claims.

## Artifacts to keep open

```text
runs/trig-live/
  result.json                 settings, status, timings, usage, witnesses
  original/driver.c            fixed input/replay driver
  original/guard.inc           original reduced guard
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
uses the original guard snapshot, including for assisted candidates.

## Rehearsal and troubleshooting

Run the focused contract tests when execution is allowed:

```bash
pytest -q tests/test_trig_demo.py
```

They use fake endpoint/container boundaries and do not require Docker or
provider access. They check input/replay contracts, response parsing, API
configuration, artifact visibility, success accounting, and error retention.
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
  does not silently substitute a canned solution.
- **`incomplete`:** inspect actual original replay logs and model restrictions.
  Invalid interfaces, failed replays, and inputs outside [2, 6] are rejected.
- **Baseline succeeds:** retain that result honestly. Rehearse on the intended
  backend; do not manufacture a missed branch or describe this run as improvement.

For a short talk, prepare a recording of an actual successful rehearsal and
keep its artifacts. If the live endpoint fails, show that recording and label
it as recorded. The runner has no canned response or fake-success mode.
If you edit model code by hand, label the run as a manual intervention.
