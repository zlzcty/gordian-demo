# Installing Gordian

## 1. Host requirements

* Linux with Docker (the user must be able to run `docker`).
* Python 3.10+.
* Optional agent CLIs: [Claude Code](https://claude.com/claude-code) (`claude`),
  [OpenAI Codex](https://github.com/openai/codex) (`codex`).

```bash
git clone <this repository> gordian && cd gordian # or download from figshare
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
gordian init            # gordian.yaml
```

## 2. KLEE backends

Gordian keeps one long-lived container per backend and bind-mounts the project
directory at `/gordian` in both.  Tool locations inside the images are probed
automatically (`runs/.docker/*.json`).

### Standard KLEE (KLEE 3.0, LLVM 13, Z3 + STP)

The public image is enough:

```bash
docker pull klee/klee:3.0
```

or build `docker/klee/Dockerfile` (adds a few host tools on top of it).

### KLEE-Float

Built from upstream `srg-imperial/klee-float` at commit `aa907655` on top of
the public `comsys/klee-dev-fpbench-prebuilt` image:

```bash
docker build -t gordian-klee-float -f docker/klee-float/Dockerfile docker/klee-float
```

(The only change relative to upstream's `scripts/patch_aachen.Dockerfile` is a
working `pacman-static` mirror.)  Building takes ~30 min.  This image has no
`llvm-profdata` (LLVM 3.4), which is why replay/coverage always runs in the
standard container; ktests are portable between the two.

KLEE-Float is optional.  The original evaluation used it for the
floating-point instances (FDLibM, floating-point logic bombs), but the shipped
target specs default to standard KLEE for all targets because KLEE-Float
crashes on many of these programs (solver-cache assertion on external
`sin`/`cos` calls).  If you do not build it, `gordian docker up --which std`
starts only the standard container; `--float` on `gordian run` selects
KLEE-Float for a target when the container exists.

### Configure and start

Before starting the containers, set the two `image:` entries in `gordian.yaml`
to the images you have.  The shipped file names the public standard image and
the tag used in the KLEE-Float build command above:

```yaml
std:
  name: gordian-klee
  image: klee/klee:3.0                # or your tag, if you built docker/klee/Dockerfile
float:
  name: gordian-klee-float
  image: gordian-klee-float:latest    # the tag you gave docker build
```

`docker images` lists the tags you have locally.  The environment variables
`GORDIAN_KLEE_IMAGE` and `GORDIAN_KLEE_FLOAT_IMAGE` override these two entries
without editing the file.

```bash
gordian docker up          # creates/starts both; `--which std` for one of them
gordian docker status
```

If a container already exists with another mount it is recreated.

## 3. Benchmarks

`gordian bench init` writes the target specs for the programs under
`benchmarks/`.  No compilation is needed up front: every run compiles the
sources it needs inside the container (bitcode for KLEE, instrumented native
objects for replay) into its own run directory.

Sanity check without any LLM:

```bash
gordian explore lb_float1_fp_l1 --budget 30     # standard KLEE
gordian explore fdlibm_e_j0 --budget 60         # standard KLEE (default for FDLibM)
gordian explore fdlibm_e_j0 --budget 60 --float # KLEE-Float, if you built it
gordian explore libyaml_parser --budget 60
```

## 4. LLM credentials

| backend | variable |
| --- | --- |
| `anthropic:*` | `ANTHROPIC_API_KEY` |
| `openai:*` | `OPENAI_API_KEY` |
| `deepseek:*` | `DEEPSEEK_API_KEY` |
| `openrouter:*` | `OPENROUTER_API_KEY` |
| `custom:*` | `OPENAI_BASE_URL` + `OPENAI_API_KEY` |
| `claude-code:*` | the CLI's login (`claude login`); a stale `ANTHROPIC_API_KEY` in the environment is ignored if rejected |
| `codex:*` | the CLI's login (`codex login`) |
| `claude-code@<provider>:<model>` | the provider's key above; the gateway listens on 127.0.0.1 only |

Any other provider or self-hosted server that speaks the OpenAI-compatible API
(vLLM, Ollama, LiteLLM, a company proxy, ...) works through your own endpoint:
either set `OPENAI_BASE_URL` and `OPENAI_API_KEY` and use `custom:<model>`, or
register it by name with `--providers extra.json`:

```json
{"myendpoint": {"base_url": "https://llm.example.com/v1", "api_key_env": "MY_LLM_KEY"}}
```

```bash
export MY_LLM_KEY=...
gordian llm test -m myendpoint:<model> --providers extra.json
```

`gordian llm test -m <spec>` verifies a backend with one short prompt.
