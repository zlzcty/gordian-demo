# Presenter notes: KLEE and Gordian on FDLibM

Companion to [DEMO.md](DEMO.md). Run commands from the repository root.
The reduced driver uses `2 <= x <= 6`; the real FDLibM sine/cosine and
their helpers are linked into KLEE and native replay.

## Requirements and preparation

| Requirement | What to prepare |
| --- | --- |
| Python 3.10+ | A virtual environment with the editable package and development dependencies |
| Docker CLI and daemon access | Permission to create/start the standard KLEE container |
| Standard KLEE image | `klee/klee:3.0`, downloaded before the talk; about 2.8 GiB compressed; allow at least 20 GiB free for download/extraction and runs |
| Mounted repository | Container `gordian-klee`, repository mounted at `/gordian`, matching `gordian.yaml` |
| Container tools | KLEE, clang, llvm-link, KLEE headers, libkleeRuntest, LLVM coverage tools checked by Gordian's tool probe |
| Architecture | Little-endian IEEE-754 binary64; rehearsal host is x86-64 |
| Model service | OpenAI-compatible API base URL, exact model ID, and a key in a named environment variable |
| Rehearsal alternative | Local mock endpoint below; no real key, provider, or model capability is tested |
| Presenter terminal | Interactive stdin for `--pause`; omit that option for automation |
| Output directory | Writable `runs/`; choose a fresh run name each time |

Normal Linux setup:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

On the mounted workspace used for this rehearsal, creating `.venv` failed
because creating the `lib64` symlink is not permitted. Use a directory on
the Linux filesystem instead. The following setup was executed successfully:

```bash
uv venv "$HOME/.venvs/gordian-demo"
uv pip install --python "$HOME/.venvs/gordian-demo/bin/python" -e '.[dev]'
. "$HOME/.venvs/gordian-demo/bin/activate"
```

`uv` is an alternative installer, not a required dependency of the demo.
If it is unavailable, use Python's venv/pip on a filesystem that supports
the needed symlinks. Do not spend presentation time installing packages.

Download the image during preparation, only when authorized:

```bash
docker pull klee/klee:3.0
```

Create a container from the already available image:

```bash
docker run --pull=never -d --name gordian-klee \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/gordian" -w /gordian \
  klee/klee:3.0 sleep infinity
```

If that container already exists with the correct mount, use
`docker start gordian-klee`. The demo itself never pulls, creates, starts,
or recreates containers. A failed container check is a setup failure, not
evidence of solver difficulty.

## Issues encountered during rehearsal

| Issue | Resolution |
| --- | --- |
| Workspace venv could not create `lib64` symlink | Put the venv under `$HOME/.venvs/`, as above. |
| Official image extraction exceeded Docker's 10 GiB disk | Enlarge the VM Docker disk to at least 30 GiB and use the official image. A local trimmed-runtime import was attempted, but has not been validated for the demo. |
| A second daemon on `/tmp` could not create writable OverlayFS layers | Use the normal daemon on its native ext4 disk after expansion; do not use the attempted second daemon for the demo. |
| Standalone clang could not find `libclang-cpp.so.13` | Include `/tmp/llvm-130-install_O_D_A/lib` in the container's `LD_LIBRARY_PATH` alongside the KLEE runtime library path. |
| No live provider credentials available | Rehearse with the explicitly labeled local HTTP mock; configure the real endpoint/model/key for production. |

These storage workarounds are specific to this workspace. On a normal machine,
use the official image and enough Docker storage. A second daemon is unnecessary.

## Production: real model

OpenRouter:

```bash
read -rs -p 'OpenRouter key: ' OPENROUTER_API_KEY
export OPENROUTER_API_KEY
python -m gordian.demo --provider openrouter \
  --model 'YOUR_PROVIDER/MODEL_ID' --name trig-production --pause
```

DeepInfra uses `--provider deepinfra` and `DEEPINFRA_API_KEY`.
For another compatible endpoint:

```bash
read -rs -p 'Endpoint key: ' MY_DEMO_KEY
export MY_DEMO_KEY
python -m gordian.demo --provider custom \
  --base-url 'https://your-service.example/v1' \
  --key-env MY_DEMO_KEY --model 'YOUR_MODEL_ID' \
  --name trig-production-custom --pause
```

The URL is the API base, not `/chat/completions`. Model IDs are provider
specific. Do not put keys in URLs, source files, notes, or command history.

## Credential-free rehearsal: explicitly mocked model

This uses the real SDK and HTTP response parser, but returns a prewritten,
clearly labeled surrogate. KLEE, compilation, and original FDLibM replay
are still real. The mock does not inject KLEE inputs or fake replay results.

Terminal A, using the configured virtual environment:

```bash
python demos/trig/mock_endpoint.py
```

Terminal B, from the same repository and environment:

```bash
GORDIAN_REHEARSAL_KEY=not-a-real-key python -m gordian.demo \
  --provider custom --base-url http://127.0.0.1:8047/v1 \
  --key-env GORDIAN_REHEARSAL_KEY --model rehearsal-mock \
  --name trig-rehearsal --pause
```

The server binds only to localhost and accepts only model `rehearsal-mock`.
Stop it with Ctrl-C after rehearsal. Do not present its response as live
LLM reasoning. Replace the endpoint/model/key settings with production
settings for the talk; the execution and replay sequence is the same.

## Talk track

1. Show `demos/trig/guard.inc`: the target is the sign of `sin(x)*cos(x)`.
2. Ask for mathematical witnesses. `sin(x)*cos(x)=sin(2x)/2` gives a negative
   product at `x=2` and a positive product at `x=4`.
3. Run baseline KLEE. Explain that it enters the linked FDLibM code, which
   contains masks, shifts, branches, argument reduction, and polynomials.
   Standard KLEE can still concretize symbolic floating-point operations.
4. Read the actual diagnostics and original-code replay outcomes. Establish
   what baseline missed; do not infer difficulty from source complexity alone.
5. Show the request, response, and diff. Only `guard.inc` changes for assisted
   exploration; the input interface and original replay executable stay fixed.
6. Explain the surrogate's safe intervals and its integer bit comparisons.
   In the mock, [2, 3] gives a negative product and [4, 4.5] a positive one.
7. Run assisted KLEE and read the ORIGINAL replay observations. The code
   generated for exploration does not get to certify its own success.
8. Finish with `result.json` and the concrete witnesses, including input
   bytes. Describe any model failure, setup error, or baseline success honestly.

## Evidence and timings

Default budgets are 10 seconds per KLEE invocation, 2 seconds per solver
query, 60 seconds for the SDK request, and up to 32 original replays per
invocation with a 2-second per-replay timeout. Compilation, tool discovery,
KLEE shutdown grace, and presentation pauses are additional.

Keep these open beside the terminal:

- `runs/<name>/result.json`: status, timings, original-code witnesses.
- `runs/<name>/baseline/klee.klee.log`: actual baseline command and diagnostics.
- `runs/<name>/llm/prompt.md` and `response.md`: exact exchange.
- `runs/<name>/surrogate.patch`: visible change.
- `runs/<name>/assisted/replay/observations.json`: original-code results.
- `runs/<name>/fdlibm/manifest.json`: linked source hashes and compiler flags.

## Validation record

- The final linked-FDLibM implementation was already committed before rehearsal.
- All 68 repository tests passed in a freshly installed virtual environment
  (Python 3.14.4; pytest 9.1.1; OpenAI SDK 3.37.0).
- A real SDK HTTP request to the local mock endpoint returned and persisted
  the labeled response; parsing produced the expected two file artifacts.
- Running before container preparation correctly returned an error without
  starting or pulling a container. Artifact: `runs/rehearsal-prerequisites/`.
- The default 10 GiB Docker data filesystem could not extract the official
  image. Source and mock tests cannot detect this setup requirement.
- Full container-based compilation, KLEE exploration, and original-code replay
  remain **pending** the VM disk expansion. These checks alone do not establish
  a successful demo. Resume using [RESTART-HANDOFF.md](RESTART-HANDOFF.md).

## Recovery

- A run name cannot be reused. Pick a new name after changing settings.
- `baseline_already_succeeds` means no improvement demonstration is available
  on that run; the model call is correctly skipped.
- `incomplete` means the checked original replays do not establish both
  outcomes. Inspect actual tests and surrogate restrictions.
- `error` means preparation or an execution step failed. Read its build/KLEE
  log; do not call it a constraint-solving failure.
- `interrupted` preserves partial artifacts; a fresh run starts over.
- Keep a recording and artifacts from a successful rehearsal. Label recorded
  or mocked material explicitly when using it as a fallback.
