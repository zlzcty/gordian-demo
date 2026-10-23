# Performing the Gordian demo

This is a walkthrough for a computer scientist new to symbolic execution and
numerical-library testing. The complete flow was rehearsed on 2026-10-22 with
the official KLEE image and a **prewritten mock model response**. Compilation,
KLEE test generation, HTTP transport, and replay were real. A live model has
not been tested. Setup details and historical issues are in [DEMO-NOTES.md](DEMO-NOTES.md);
the runner reference is [DEMO.md](DEMO.md).

## 1. Understand the experiment

Your task is to generate inputs taking both sides of `sin(x)*cos(x) < 0`,
with one double constrained to `2 <= x <= 6`. Outcome 1 means negative;
outcome 2 means nonnegative. Angles are in radians.

FDLibM is a C mathematical library. This predicate comes from its implementation
of `j0`, a Bessel function used in mathematical physics. You do not need Bessel
function theory: the demo extracts one branch decision and removes calculations
that only contribute to the function's final answer. It does not compute or
validate the complete Bessel function. Open `demos/trig/guard.inc` to see the
reduction; the real FDLibM sine/cosine implementations and helpers are linked.

KLEE executes LLVM bitcode with symbolic inputs, accumulating path constraints
and asking a constraint solver for concrete inputs. A `.ktest` stores such an
input. Multiple execution paths can lead to the same target branch outcome.
Our baseline produced two tests but covered only one of the two outcomes.

The limitation here is standard KLEE's symbolic floating-point handling.
“Concretizing” means choosing a concrete value for a symbolic expression, losing
exploration freedom at that operation. This run finished quickly with a missing
outcome; it did not time out on a difficult trigonometric solver query.

Gordian asks for an easier replacement, called a surrogate or ghost code, to
explore instead. It then runs the resulting inputs through the fixed original
program. A bad surrogate can lose useful inputs or propose incorrect outcomes;
original replay establishes what each candidate actually does.

The mathematical shortcut is `sin(x)*cos(x) = sin(2*x)/2`. At 2 the product
is about -0.3784; at 4 it is about +0.4947. Both are far from zeros, where
floating-point rounding complicates exact-real reasoning. These values explain
the example; the runner does not preload them as test cases.

The mock restricts exploration to [2,3] and [4,4.5], then compares integer
encodings of doubles. Positive finite IEEE-754 binary64 values have the same
ordering as their unsigned bit encodings. `memcpy` reinterprets the bytes;
it is not a numeric cast to an integer. `klee_assume` prunes values outside
the two intervals. This is a deliberately restricted search aid, not an
implementation equivalent over the entire domain.

## 2. Prepare before presenting

Use Linux with Docker CLI/daemon access, Python 3.10+, and a writable checkout.
The container supplies KLEE 3.0, matching clang/LLVM 13, KLEE headers, runtime
replay library, and coverage tools required by discovery. KLEE-Float, a host C
compiler, agent CLIs, and the full benchmark setup are unnecessary for this flow.

Allow a Docker data filesystem of at least 30 GiB with about 20 GiB free before
pulling. Check its actual location with `docker info`; this machine uses
`/var/lib/docker`. The image occupies about 13 GiB including retained image
content after extraction here. Host workspace free space cannot compensate for
a full Docker filesystem.

Run from the `gordian` repository root in each terminal. Install the Python
package once (choose a venv directory supporting Linux symlinks):

```bash
python3 -m venv "$HOME/.venvs/gordian-demo"
. "$HOME/.venvs/gordian-demo/bin/activate"
pip install -e '.[dev]'
```

If Python reports missing `ensurepip`, install your distribution's Python venv
package, or use `uv` if available:

```bash
uv venv "$HOME/.venvs/gordian-demo"
uv pip install --python "$HOME/.venvs/gordian-demo/bin/python" -e '.[dev]'
. "$HOME/.venvs/gordian-demo/bin/activate"
```

This workspace rejects venv symlinks inside the checkout, so the external
location above matters. `uv` itself is optional.

Prepare the official image and container before the talk:

```bash
docker pull klee/klee:3.0
docker run --pull=never -d --name gordian-klee \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/gordian" -w /gordian \
  klee/klee:3.0 sleep infinity
```

If the correctly mounted container already exists, run `docker start gordian-klee`
instead. Verify it with `docker inspect gordian-klee`: it must be running and
mount this exact repository at `/gordian`, consistent with `gordian.yaml`.
The demo checks prerequisites but never pulls images or starts containers.

```bash
docker exec gordian-klee bash -lc 'klee --version; clang --version; llvm-link --version'
pytest -q
```

All 68 tests passed here. They check contracts; only running the demo checks
the complete toolchain. The official image needed no library-path workaround.

## 3. Rehearse the complete flow

Terminal A, with the venv activated:

```bash
python demos/trig/mock_endpoint.py
```

Leave it running. It binds to localhost port 8047 and accepts model
`rehearsal-mock`. If that port is occupied, check for an existing mock process.

Terminal B, same directory and venv:

```bash
GORDIAN_REHEARSAL_KEY=not-a-real-key python -m gordian.demo \
  --provider custom --base-url http://127.0.0.1:8047/v1 \
  --key-env GORDIAN_REHEARSAL_KEY --model rehearsal-mock \
  --name my-rehearsal --pause
```

Choose a fresh name for every attempt. There are three Enter pauses. For an
automated rehearsal, omit `--pause`; piping newlines does not work because the
runner explicitly requires a terminal for pauses. To capture unattended output,
use `set -o pipefail` and append `2>&1 | tee runs/my-rehearsal-terminal.log`.

## 4. Present it, screen by screen

Allocate about 5–8 minutes for explanation. The automated flow measured 8.18
seconds on this machine; model latency and presentation pauses add time.

**Before the first Enter:** open `demos/trig/guard.inc`. Say: “We want inputs
for both outcomes of this numerical branch. A person can use a trig identity;
KLEE executes the instructions implementing the numerical library.” State that
this run uses a mock model response. Press Enter to run baseline exploration.

**At the second pause:** read the concretization diagnostic and original replay
lines. In the rehearsal they were `x=2 -> outcome 1` and
`x=2.375 -> outcome 1`. Say: “Two tests are not two target outcomes. Both replay
on the negative side; outcome 2 is missing.” The baseline took 1.27 seconds,
produced two tests, and reported zero errors. This is observed incomplete branch
coverage, not proof that no baseline configuration could find the other branch.
Press Enter to request the surrogate.

**At the third pause:** the complete response and unified diff have printed.
Open `runs/<name>/llm/prompt.md` and `surrogate.patch`. Explain that the request
contains the guard, domain, missing outcome, and diagnostics. The response
replaces only `guard.inc`; the input driver and original replay executable
stay fixed. Point to the safe intervals and integer comparisons described
above. Say: “This response is prewritten for rehearsal. KLEE still has to
solve the constraints and generate its own concrete inputs.” Press Enter.

**At completion:** point to the ORIGINAL REPLAY lines. In the rehearsal the
assisted tests were `x=2 -> outcome 1` and `x=4 -> outcome 2`. Assisted KLEE took
1.20 seconds, produced two tests, and reported zero errors. Say: “The replacement
helped discover a new input, and the original numerical implementation confirms
the missing branch. The replacement does not certify itself.”

Open `runs/<name>/result.json` and locate `status`, `baseline_witnesses`,
`assisted_witnesses`, and `elapsed_seconds`. `improved` means both original
outcomes were witnessed and at least one was missing before assistance.
It does not prove surrogate equivalence, exhaustive coverage, faster execution
in general, or live model capability. This focused runner demonstrates the
surrogate stage, not Gordian's full partitioning/inversion pipeline or the
paper's evaluation.

## 5. Inspect the saved evidence

The completed automated run is `runs/rehearsal-full-auto/` in this workspace.
Its terminal transcript is `runs/rehearsal-full-auto-terminal.log`.

| Evidence | Where to look under that run |
| --- | --- |
| Exact original input interface and guard | `original/driver.c`, `original/guard.inc` |
| Unmodified linked math sources and hashes | `fdlibm/manifest.json`, `fdlibm/*.c` |
| Baseline command and concretization warning | `baseline/klee.klee.log` |
| Exact HTTP prompt and mock response | `llm/prompt.md`, `llm/response.md` |
| Generated change | `surrogate.patch` |
| Original replay for assisted tests | `assisted/replay/observations.json` and per-test logs |
| Final decision and witnesses | `result.json` |

The accepted input bytes were `0000000000000040` for 2 and
`0000000000001040` for 4, in little-endian order. Native replay uses the same
snapshot of ten FDLibM sources as baseline and assisted builds. Namespaced
symbols and disabled external math fallback prevent accidental system-libm
substitution. The native executable always contains the original guard.
Run artifacts are ignored by Git; copy them separately if moving the presentation.

## 6. Switch to a live model when ready

Start from a successfully rehearsed environment. For OpenRouter:

```bash
read -rs -p 'OpenRouter key: ' OPENROUTER_API_KEY
export OPENROUTER_API_KEY
python -m gordian.demo --provider openrouter \
  --model 'YOUR_PROVIDER/MODEL_ID' --name my-live-demo --pause
```

For DeepInfra use `--provider deepinfra`, its exact model ID, and
`DEEPINFRA_API_KEY`. Other OpenAI-compatible services use `--provider custom`,
`--base-url`, and `--key-env` as in the mock command. Use the API base URL,
not the chat-completions path. The real service must be reachable and the key
must have access to that model. No live credentials were available here, so
rehearse this step separately before claiming a live-model result. There is
one request and no automatic repair loop.

## 7. Handle deviations honestly

If baseline already covers both outcomes, the runner skips the model and
reports `baseline_already_succeeds`. Retain that result; different tools may
explore differently. No domain change was needed in our successful rehearsal.

If the result is `incomplete`, inspect original replay observations and the
surrogate restrictions. If it is `error`, read build, endpoint, or KLEE logs;
a broken toolchain does not demonstrate a solver limitation. Reusing a run name
is rejected. Interrupted and failed runs retain partial evidence.

The earlier failures were disk exhaustion on the old 10 GiB Docker filesystem,
a failed second-daemon OverlayFS workaround, unsupported workspace venv
symlinks, missing Python `ensurepip` after restart, and the invalid piped-pause
command. The expanded normal Docker daemon and the venv above resolved setup;
no source-code fix was required. See the issue table in DEMO-NOTES.md.

After rehearsal stop the mock with Ctrl-C in terminal A. Keep successful
artifacts and, if desired, make a recording before the talk. Label recorded
or mocked material explicitly if using it as a fallback.
