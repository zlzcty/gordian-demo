# Restart handoff: FDLibM KLEE/Gordian demo

## Resume here

Repository: `/c/TempProjectWork/codex-work-1/gordian`.
Branch: `demo/trig-klee-gordian`. User requested a graceful stop for a VM
restart with more disk. **Do not continue testing until the user resumes.**
Increase the disk backing `/var/lib/docker` to **at least 30 GiB**.
It is currently a 10 GiB virtual disk (`vdd`), with a 9.8 GiB ext4 filesystem;
there is no unused device capacity to grow into. After the host expands it,
check whether the filesystem also expanded. The block device was not exposed
as `/dev/vdd` inside this environment, despite appearing in `lsblk`.

Original task: finish committing the linked-FDLibM demo, actually rehearse its
entire flow, and write concise presenter notes with prerequisites and issues/fixes.
User authorized execution and pulling **`klee/klee:3.0`**. User has no model
credentials here and explicitly requested a **mock response**; production
endpoint/model/key will be configured later. No need to ask again for these
authorizations. Do not present the mock as evidence of live LLM capability.

## Implementation and commits already complete

- `76b6a0e`: link the actual ten-source FDLibM sin/cos dependency closure.
- `87db51e`: source snapshot and consistent build-binding contract tests.
- `e1f073a`: guide for linked FDLibM execution and original-code replay.
- `c819800`: explicitly labeled local OpenAI-compatible mock endpoint/fixture.
- `74a2b73`: mock endpoint tests.
- Earlier commits implement the focused runner, endpoint settings, example,
  evidence validation, presenter guide, and robustness fixes.

`gordian/demo/` separates CLI/environment, HTTP/model boundary, pure evidence
transformations, FDLibM snapshotting, container execution, and workflow.
The runner never starts/pulls containers. It prints/saves the full model response,
source diff, KLEE diagnostics, and original-code replay observations.
Only the guard is replaced for assisted exploration. Both variants link the same
immutable FDLibM snapshot; every accepted witness replays on the fixed ORIGINAL
native executable. External math fallback is disabled; native replay has no `-lm`.

Read `DEMO.md`, `DEMO-NOTES.md`, and `demos/trig/PLAN.md`.
An unrelated untracked `fdlibm-trig-demo.md` must be preserved and left out of
our commits. Do not revert unrelated work. Stage only explicit demo files.
Git identity is unset; prior commits used:

```bash
git -c user.name=Codex -c user.email=codex@users.noreply.github.com commit -m '...'
```

## What actually passed

- All **68 repository tests** passed in a fresh environment: Python 3.14.4,
  pytest 9.1.1, OpenAI SDK 3.37.0.
- CLI help worked. An invocation without a prepared container correctly refused
  execution and saved `runs/rehearsal-prerequisites/result.json`.
- Real OpenAI SDK HTTP requests to the local mock succeeded and saved/parsed
  the labeled fixture: `runs/rehearsal-http/` and `runs/rehearsal-http-current/`.
- Requirements snapshot: `runs/rehearsal-requirements.txt` (ignored artifacts).
- Standalone KLEE 3.0 and clang 13.0.1 version probes worked in a chroot of the
  trimmed image root. Clang needed the bundled LLVM library search path.

**NOT yet verified:** demo native compilation, bitcode compilation, baseline
KLEE exploration, assisted KLEE exploration, original-code replay, improvement,
and full-flow duration. No successful full-demo result exists. Do not claim one.

## Environment and setup attempts

Fresh working Python environment: `/home/agent/.venvs/gordian-demo`.
If lost on restart, recreate (or use python3 venv/pip in that location):

```bash
uv venv "$HOME/.venvs/gordian-demo"
uv pip install --python "$HOME/.venvs/gordian-demo/bin/python" -e '.[dev]'
. "$HOME/.venvs/gordian-demo/bin/activate"
```

Creating `.venv` in the workspace failed because the mount disallowed the
`lib64` symlink. A partial ignored `.venv` may remain; use the environment above.
Old environment `/tmp/gordian-analysis-venv` is unnecessary.

Docker issues and current state:

1. Default daemon `/var/run/docker.sock`, originally no images/containers.
   Official image extraction failed twice due to insufficient disk. The image
   is ~2.8 GiB compressed, ~11 GiB extracted, requiring additional working space.
2. An isolated daemon at `unix:///tmp/gordian-docker.sock` downloaded the image
   under `/tmp/gordian-docker-data`, but could not create writable OverlayFS
   layers on the root filesystem (itself OverlayFS). Attempts to relocate the
   snapshotter were unsuccessful. **Do not resume using this daemon.**
3. A trimmed root was assembled from the downloaded official layers using rsync,
   omitting `/tmp/llvm-130`, top-level LLVM install `lib/*.a`, and KLEE unittests.
   Compiled binaries were preserved. Root: `/c/TempProjectWork/klee-runtime-root`.
   It was successfully imported into the DEFAULT daemon as
   `gordian-klee-runtime:3.0-rehearsal`, image ID prefix `868e6534cbcd`.
   Imported content ~1.32 GB, extracted ~3.6 GB. It is **not full-flow validated**.
4. A container creation was attempted with this runtime immediately before
   stopping. Last observed: `gordian-klee` exists in **Created** state, not running.
   Inspect it after restart; do not mistake its existence for a ready container.
   Default Docker disk then used 4.8 GiB with 4.5 GiB free.

Prefer the unmodified official image after expanding storage. The trimmed image
can be removed if needed, but first verify no desired container depends on it.
Never blanket-prune Docker. A created `gordian-klee` from this attempt can be
explicitly removed/recreated for the official-image rehearsal.

Temporary paths (may disappear on restart):

- `/tmp/gordian-docker-layers/snapshots/{1..17}/fs`: original extracted layers.
- `/tmp/gordian-docker-data`: isolated daemon image content.
- `/tmp/gordian-docker-exec`, `/tmp/gordian-docker.pid`, `/tmp/gordian-dockerd.log`.
- `/var/lib/docker/gordian-demo-snapshotter`: attempted relocation metadata and
  symlinks; not used by the default daemon's actual snapshotter.
- Two attempted bind mounts may target the isolated snapshotter directory.
  Restart should clear these temporary mounts/processes.

Official image provenance from the isolated daemon:
`sha256:8f76ff8a820e255b5b6503eb84dfb2e9e48dae52f46b6d82d1e67e492f63f2d2`.
KLEE revision `dfa53ed4f5711ee2d378abb267bff1da8623f7e7`, LLVM 13.0.1.
Do not put large image files or extracted roots into the Git repository.

## Next actions after user resumes

1. Check `df -h /var/lib/docker`, daemon access, and existing container state.
   Use the NORMAL socket (`unset DOCKER_HOST`), not the attempted isolated daemon.
2. Prepare the official image/container per `DEMO.md` after expansion. The user
   already authorized its pull. Verify KLEE/clang/llvm-link versions agree.
   The image contains LLVM 13 under `/tmp/llvm-130-install_O_D_A`.
   If needed, include its `lib` directory in `LD_LIBRARY_PATH` alongside
   `/home/klee/klee_build/lib`; keep the matching LLVM bin directory discoverable.
   Container must mount this repository at `/gordian`, named `gordian-klee`.
3. Start the local mock in terminal A:

   ```bash
   python demos/trig/mock_endpoint.py
   ```

   Port 8047, localhost only, model ID `rehearsal-mock`. Check for an existing
   listener before starting; the former server may have ended before shutdown.
4. Rehearse the exact full flow in terminal B, saving the transcript:

   ```bash
   set -o pipefail
   printf '\n\n\n' | GORDIAN_REHEARSAL_KEY=not-a-real-key \
     python -m gordian.demo --provider custom \
     --base-url http://127.0.0.1:8047/v1 \
     --key-env GORDIAN_REHEARSAL_KEY --model rehearsal-mock \
     --name rehearsal-full --pause | tee runs/rehearsal-full-terminal.log
   ```

   This simulates the three Enter pauses. For live presenting, use interactive
   stdin instead of the `printf` pipe. Choose a fresh name after every attempt.
5. Fix real compilation/runtime failures, then rerun relevant tests. Commit each
   meaningful fix separately. Retain error artifacts; never label setup failures
   as solver difficulty. Report actual baseline and assisted replay witnesses.
6. Update `DEMO-NOTES.md` with actual timings/results and short issues/fixes.
   Commit the final notes. Stop the mock service when finished.

### Potential demo design issue to check with actual evidence

Current input domain is **[2, 6]**. Baseline KLEE might already cover both signs,
because FDLibM has an integer argument-reduction branch near 3*pi/4 before
symbolic FP concretization. The runner correctly skips the model if baseline
already succeeds. Do not fake missing coverage.

If this actually happens, consider focusing the domain to **[2.5, 6]**, avoiding
that early split while retaining easy witnesses x=3 (negative) and x=4 (positive).
Update driver lower-bound bits (`0x4004000000000000`), input validator/tests,
prompt, fixture interval explanation, and guides together. Only do this based on
real rehearsal evidence, and explain the focused domain honestly.

The mock currently retains safe intervals [2,3] and [4,4.5] using integer bit
comparisons and `klee_assume`. It does not generate/inject test cases; actual
KLEE must produce them and original FDLibM replay must validate them. No live
provider/model capability has been tested. Production uses the same runner with
OpenRouter, DeepInfra, or a custom OpenAI-compatible URL and named key variable.
