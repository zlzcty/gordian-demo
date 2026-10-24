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

## 3. Check readiness

The demo now has three independent commands: `baseline`, `generate`, and
`assisted`. Each command finishes and returns to the shell. There are no Enter
pauses in these modes. The old combined invocation remains available for
compatibility, but use the commands below for presenting.

First check local execution requirements:

```bash
python scripts/check_demo.py
# Equivalent: python -m gordian.demo check
```

It prints simple labels such as `Container: OK` or `Build: FAIL`, and exits
nonzero if any check fails. It checks Python/packages, settings, Docker CLI,
container state, repository mount, executable tools, target files, output access,
and actual native and bitcode compilation. Build checks use a temporary directory
under `runs/` and remove it afterward. This check never starts containers.

To check model settings too, supply the same provider options as generation:

```bash
GORDIAN_REHEARSAL_KEY=not-a-real-key python scripts/check_demo.py \
  --check-model --provider custom --base-url http://127.0.0.1:8047/v1 \
  --key-env GORDIAN_REHEARSAL_KEY --model rehearsal-mock
```

`Model` checks URL syntax and a model setting; `Key` checks a nonempty named
variable. These checks do not establish remote access. Add `--probe-model` to
query the endpoint's model listing and check that the configured ID appears.
That also checks model/key settings; it makes no completion request. Some
compatible providers do not expose model listings, and a listing does not prove
completion permission or response quality. Actual generation is the final check.

## 4. Start the rehearsal service

Terminal A, in this repository with the venv activated:

```bash
python demos/trig/mock_endpoint.py
```

Leave it running. It binds to localhost port 8047 and accepts model
`rehearsal-mock`. This is an explicitly labeled, prewritten response, not a live
LLM. If the port is in use by your earlier practice server, stop that server or
choose another port with `--port 8048` and change all base URLs accordingly.

Terminal B, same directory and venv, runs the three stages below. Choose fresh
names each time; stages refuse overwrites. `--from-run` is the actual directory
of the previous stage, not just its name.

## 5. Baseline: run KLEE without ghost code

```bash
python -m gordian.demo baseline --name practice-baseline
```

Show the original guard, concretization diagnostic, and original replay output.
In the rehearsal:

```text
ORIGINAL REPLAY: x=2 -> outcome 1
ORIGINAL REPLAY: x=2.375 -> outcome 1
Missing outcomes: [2]
```

Say: “KLEE explored two paths and generated two tests. Both tests take the
negative-product branch. Standard KLEE concretized the symbolic floating-point
calculation, so this run did not find a witness for the other branch.”

This is observed missing coverage, not proof that every baseline configuration
must fail. If baseline covers both outcomes, it reports
`baseline_already_succeeds`; do not claim improvement. A successful baseline
command exits 0 whether it misses outcomes or covers them all. Build/runtime
failures exit nonzero and are not evidence of solving difficulty.

Open `runs/practice-baseline/result.json`. Its `baseline.witnesses` and
`missing` fields record the result. The code, helper sources, target settings,
and hashes are snapshotted here for later stages.

## 6. Generate: request ghost code separately

```bash
GORDIAN_REHEARSAL_KEY=not-a-real-key python -m gordian.demo generate \
  --from-run runs/practice-baseline --name practice-ghost \
  --provider custom --base-url http://127.0.0.1:8047/v1 \
  --key-env GORDIAN_REHEARSAL_KEY --model rehearsal-mock
```

This performs one HTTP model request, prints the complete public response and
diff, and saves them. It does not compile or invoke KLEE and needs no running
Docker container. The request uses the original snapshot, baseline diagnostics,
and missing outcomes. Generation does not rerun baseline.

Open `runs/practice-ghost/llm/prompt.md`, `llm/response.md`, and
`surrogate.patch`. Explain: “The response replaces the numerical calculation
with integer bit comparisons and restricts exploration to [2,3] and [4,4.5].
KLEE can keep those operations symbolic. The first interval returns outcome 1,
the second outcome 2. The response supplies this mathematical shortcut;
KLEE does not independently discover or prove the intervals.”

The input driver and original code stay fixed. The generated function cannot
replace the driver or introduce new symbolic objects under the response contract.
The contract is a format/interface check, not a proof of equivalence.

To change the LLM, change only this stage's endpoint/model/key options. For
OpenRouter, for example:

```bash
read -rs -p 'OpenRouter key: ' OPENROUTER_API_KEY
export OPENROUTER_API_KEY
python -m gordian.demo generate \
  --from-run runs/practice-baseline --name practice-live-ghost \
  --provider openrouter --model 'YOUR_PROVIDER/MODEL_ID'
```

DeepInfra uses `--provider deepinfra` and `DEEPINFRA_API_KEY`. Other
OpenAI-compatible providers use `--provider custom --base-url ... --key-env ...`.
Use the API base URL, not its chat-completions path. Generation has one request,
a timeout and no automatic repair loop. You can generate multiple alternatives
from one baseline by choosing different output names. Live-model performance
has not been tested here.

## 7. Assisted: run KLEE with ghost code and replay the results

```bash
python -m gordian.demo assisted \
  --from-run runs/practice-ghost --name practice-assisted
```

This stage requires Docker but no API key, model service, or model selection.
It compiles the replacement, runs KLEE, then replays every checked test using
a freshly built ORIGINAL executable. Both builds use the same helper snapshot.
The generated driver is reconstructed from the fixed original driver; the
original guard is never replaced in the replay executable.

Expected rehearsal output:

```text
ORIGINAL REPLAY: x=2 -> outcome 1
ORIGINAL REPLAY: x=4 -> outcome 2
SUCCESS
```

`SUCCESS` means the assisted tests have valid original-code replay witnesses
for **all required outcomes**. It is not enough for the surrogate to return both
labels. If assisted original replay does not cover them all, it prints
`INCOMPLETE` and exits 1. `result.json` includes `assisted.witnesses`, the original
baseline evidence, and `added_outcomes`, so improvement can be distinguished
from a baseline that already covered everything. SUCCESS does not require a
baseline failure, and it does not claim equivalence or exhaustive input ranges.

Say: “The ghost code helped KLEE generate a new candidate. Running that input
through the original numerical code confirms the missing branch.”

Stop the mock in terminal A with Ctrl-C afterward. The KLEE container can stay
running for further practice.

## 8. Change the target without editing stage orchestration

Pass a target description to baseline:

```bash
python -m gordian.demo baseline \
  --target demos/trig/target.json --name another-baseline
```

Copy that JSON and its driver/guard to a new example directory to target another
fragment. Paths inside the JSON are relative to that JSON file. Configure:

| Field | Purpose |
| --- | --- |
| `driver`, `guard` | Fixed harness source and replaceable fragment; the driver includes `guard.inc` |
| `function` | Replacement function name, with signature `static int NAME(double x)` |
| `library` | Directory holding helper sources and headers |
| `sources`, `headers` | Plain, unique filenames to snapshot from that directory; empty lists are supported |
| `cflags` | Shared native/bitcode compiler options, including any symbol renaming |
| `instructions` | Target-specific context, semantics, and hints for the model |
| `input` | Symbolic object name, `binary64-le` format, and numeric `min`/`max` |
| `replay_prefix` | Prefix for the driver's native output: `PREFIX x=... outcome=...` |
| `outcomes` | Integer branch labels that assisted original replay must cover |

The adapter currently supports **one bounded little-endian binary64 symbolic
input** and an integer outcome. This is an explicit scope boundary. Structured,
multiple, or string inputs need a new input/replay adapter. Stage orchestration
and model transport do not need target-specific changes for other targets
within this contract. Helper sources may be empty; the FDLibM closure is not
hardcoded in the new stage executor.

Keep the JSON contract consistent with the C driver: input name, domain,
function call, and replay output must agree. Changing bounds in JSON alone does
not rewrite C. The native/bitcode build check catches build failures, while
replay validation rejects incompatible test objects or observations.

Only baseline accepts `--target`. Later stages inherit and verify the frozen
snapshot through `--from-run`. Changing checkout code afterward does not change
an existing experiment. Edited original snapshots or generated guards are
rejected; make a fresh baseline or generation instead of editing artifacts.

## 9. Artifacts and actual rehearsal record

Each stage has its own `result.json`, settings, timing, and retained error
artifacts. Code snapshots live under `original/`, `library/`, and `target.json`;
`snapshot.json` records their hashes. Baseline and assisted runs also contain:

- `native/build.log` and `native/original-replay`.
- `exploration/build/build.log` and `exploration/klee.klee.log`.
- `exploration/klee/*.ktest`, `warnings.txt`, and `messages.txt`.
- `replay/observations.json` and per-test replay logs.

Generation contains `llm/prompt.md`, `llm/response.md`, `surrogate/guard.inc`,
`surrogate/notes.md`, and `surrogate.patch`. Artifacts are ignored by Git;
copy them separately if moving the presentation.

The split workflow was rehearsed in this VM using `runs/modular-final-baseline/`,
`runs/modular-final-ghost/`, and `runs/modular-final-assisted/`. The mock was on
port **8048** to avoid disturbing any existing practice server. The requirements
transcript is `runs/modular-check-final.log`; terminal transcripts are
`runs/modular-final-*-terminal.log`. Actual outcomes were baseline 2 and 2.375
(both 1), assisted 2 (1) and 4 (2), followed by SUCCESS. Both KLEE invocations
produced two tests with zero errors.

The older combined flow was rehearsed in `runs/rehearsal-full-auto/` in 8.18
seconds; its five-step pauses and artifact layout apply only to the legacy
combined invocation. The split commands return to the shell between stages.

## 10. Recover from problems

A run name cannot be reused. Failed stages retain their logs and error status;
retry into a new directory. Generation can reuse the same completed baseline,
and assisted execution can reuse the same completed generation.

Do not feed a failed or wrong-stage directory to the next command. Do not
interpret `error`, compilation failures, or invalid replay observations as
constraint-solving difficulty. Inspect actual original replay evidence if
assisted execution reports `INCOMPLETE`.

Setup issues from the first rehearsal included insufficient Docker disk space,
workspace venv symlinks, and missing Python ensurepip. For the new checker,
LLVM 13's `llvm-profdata --version` was a false failure; executable probes now
use `--help`. The normal official image, expanded Docker disk, and external
venv work here. See DEMO-NOTES.md for the complete issue record.
