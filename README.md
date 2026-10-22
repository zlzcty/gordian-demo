<table width="100%"><tr><td width="180" valign="top"><img src="images/logo.svg" alt="Gordian logo" width="160"/></td>
<td valign="top"><h1>Gordian</h1><p><strong>LLM-generated ghost code for KLEE symbolic execution</strong></p></td></tr></table>

Gordian adds a layer on top of KLEE: an LLM writes *ghost code* that makes
solver-hostile programs tractable, KLEE does the exploring, and every test
case is validated by replaying it on the **unmodified** program.  Three kinds
of ghost code are generated, in sequence, on whatever is still uncovered:

| technique | what the LLM writes | when it helps |
| --- | --- | --- |
| **semantic partitioning** | a harness that constrains the heap / structured input to a few *semantic topologies* (concrete shape, symbolic values) selected by a fresh symbolic `klass` | heap-shape or input-structure explosion |
| **surrogate models** | a solver-friendly rewrite of the difficult fragments (transcendental math, crypto, I/O, bit tricks, threads) with the same symbolic input interface | the fragment itself defeats the solver |
| **ghost inversion** | the fragment replaced by a havoc, plus `inverse.py` / `forward.py`; proposals are reconciled with the path condition by bidirectional constraint propagation (Z3 optimisation on KLEE's path conditions, then sampling and KLEE with relaxed bounds) | the target is guarded by the *output* of a localized, invertible computation |

The LLM can be driven three ways, all through the same `-m` option:
**Claude Code** (agent), **Codex** (agent), or a **standalone API**
(Anthropic, OpenAI, DeepSeek, or any OpenAI-compatible endpoint).

## About this release

This is the latest, refactored version of Gordian.  The research prototype
 has been rewritten as one installable package
with a single `gordian` command, so that others can use it on their own
programs: agent backends (Claude Code, Codex) that compile, test and repair
their own ghost code; use through the `claude` / `codex` CLI login as well as
API keys; any OpenAI-compatible provider; a target-spec format for adding new
programs; and per-run reports.  The three ghost-code techniques are described in detail in
the paper.

## 1. Install

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
gordian init                 # writes gordian.yaml (edit the image names if yours differ)
gordian docker up            # creates gordian-klee (KLEE 3.0) and gordian-klee-float, mounts this directory at /gordian
gordian bench init           # writes benchmarks/targets/*.yaml (149 targets: LogicBombs, FDLibM, bc, jq, libexpat, libyaml;
                             # "bc" is Gavin D. Howard's bc with the GNU bc extensions, called "GNU bc" for simplicity)
gordian explore lb_sin_ef_l2 --budget 60   # KLEE only, no LLM: checks the containers work
```

See `INSTALL.md` for the Docker images (the standard backend is the public
`klee/klee:3.0`; KLEE-Float is built from `docker/klee-float/Dockerfile`).

## 2. Using Gordian with Claude Code

Requires the `claude` CLI, logged in (`claude login`), or `ANTHROPIC_API_KEY`
set.  Claude Code gets a scratch directory with the annotated sources, writes
the ghost code with its own tools, compiles and tests it before answering,
and repairs compile errors itself.

```bash
gordian llm test -m claude-code:claude-sonnet-5-5          # one short prompt, verifies the login
gordian run lb_sin_ef_l2   --budget 600  -m claude-code:claude-sonnet-5-5
gordian run fdlibm_e_j0    --budget 900  -m claude-code:claude-sonnet-5-5
gordian run libyaml_parser --budget 1800 -m claude-code:claude-sonnet-5-5
```

Options: `--effort low|medium|high|xhigh|max`, `--max-budget-usd 2.0` (spend
cap per LLM task).  A stale `ANTHROPIC_API_KEY` in the environment is ignored
if the API rejects it and the CLI login is used instead.

Claude Code can also drive a non-Anthropic model.  Gordian ships a small
gateway that translates the Anthropic Messages API to an OpenAI-compatible
endpoint, so Claude Code's tools work unchanged while the model is e.g.
DeepSeek:

```bash
export DEEPSEEK_API_KEY=...
gordian run libyaml_parser --budget 1800 -m claude-code@deepseek:deepseek-chat
```

(`claude-code@<provider>:<model>` works for every provider listed in section 4.)

## 3. Using Gordian with Codex

Requires the `codex` CLI, logged in (`codex login`) or `OPENAI_API_KEY` set.
Codex runs headless in a `workspace-write` sandbox on the task directory.

```bash
gordian llm test -m codex:default                          # the model configured in ~/.codex/config.toml
gordian run lb_sin_ef_l2   --budget 600  -m codex:default
gordian run bc_num         --budget 1800 -m codex:gpt-6-luna   # or any model your Codex account offers
```

`--effort low|medium|high` maps to Codex's `model_reasoning_effort`.

## 4. Using Gordian with a standalone API

No agent CLI needed; each task becomes one prompt (the input files are inlined,
the model answers with fenced file blocks).  Responses are cached on disk
(`llm_cache/`).

| spec | endpoint | credential |
| --- | --- | --- |
| `anthropic:claude-sonnet-5-5` | Anthropic API | `ANTHROPIC_API_KEY` |
| `openai:gpt-5` | OpenAI API | `OPENAI_API_KEY` |
| `deepseek:deepseek-chat` | api.deepseek.com | `DEEPSEEK_API_KEY` |
| `openrouter:<model>` | openrouter.ai | `OPENROUTER_API_KEY` |
| `custom:<model>` | `$OPENAI_BASE_URL` (any OpenAI-compatible server) | `OPENAI_API_KEY` |

```bash
export ANTHROPIC_API_KEY=...
gordian llm test -m anthropic:claude-sonnet-5-5
gordian run lb_sin_ef_l2 --budget 600 -m anthropic:claude-sonnet-5-5 --temperature 0.5

export DEEPSEEK_API_KEY=...
gordian run fdlibm_e_j0 --budget 900 -m deepseek:deepseek-chat
```

More providers: `--providers extra.json` with `{"name": {"base_url": "...", "api_key_env": "..."}}`.
`gordian llm list` prints the full list.

## 5. What a run produces

`runs/<name>/` holds `report.md` / `report.json` (coverage, which stage added
what, triage of the uncovered regions, LLM usage), `state.json`, `gordian.log`,
every prompt and response (`llm/`), and the ghost code of each stage
(`01_partition/`, `02_rewrite/`, `03_inversion/`).  KLEE outputs and the
replayed test suite are deleted at the end of a run unless `--keep-tests` is
given.  `gordian report runs/` tabulates all runs; `python
scripts/summarise_results.py out/ --runs runs/` writes a summary table of your own runs
(`SUMMARY.md`, `summary.json`) to `out/`.

The pipeline:

```
explore    short KLEE run on the original program, solver timeout cut by 90 %  -> uncovered lines, ranked regions
partition  ghost harnesses with semantic topologies (2 rounds, the 2nd with feedback), KLEE, replay
rewrite    LLM triage of the uncovered regions, surrogate model of the difficult fragments (2 rounds), KLEE, replay
inversion  for regions triaged as invertible: ghost program, inverse/forward, bidirectional propagation, replay
```

Every KLEE run gets a wall-clock slice of `--budget` with a soft kill, every
ghost run also receives KLEE's own diagnostics from earlier runs (concretized
floating-point values, external calls), and every test is replayed on a
natively compiled, coverage-instrumented build of the original sources
(8 in parallel, with a per-test timeout).  If a KLEE run produces tens of
thousands of tests and replay time matters more than exactness,
`--replay-max-tests N` (or `replay_max_tests` in `gordian.yaml`) replays an
evenly spaced sample of at most N tests per run; the default, 0, replays all.

### Standard KLEE vs. KLEE-Float

Two symbolic-execution backends are shipped: standard KLEE 3.0 (Z3 or STP)
and KLEE-Float (Z3), a fork with precise floating-point reasoning.  In the
original evaluation the floating-point instances (FDLibM and the floating-point
logic bombs) were run on KLEE-Float, and the paper's results were
obtained that way.  For the distributed tool we recommend, and default to,
standard KLEE for every target, including FDLibM, because the KLEE-Float
fork (LLVM 3.4, 2017) crashes on many of these programs (a solver-cache
assertion on external `sin`/`cos` calls), is far slower, and has no coverage
tooling of its own.  Standard KLEE concretizes a symbolic double at the first
floating-point operation; Gordian feeds those concretization warnings to the
LLM, which then writes ghost code that decides the guards on the integer bit
patterns, so coverage on floating-point code does not depend on the
floating-point solver.  To use KLEE-Float anyway, pass `--float` to
`gordian run` / `gordian explore` or set `float: true` in the target spec.

## 6. Adding a program

Write a target spec (every field is documented in `gordian/targets.py`):

```yaml
# benchmarks/targets/mylib_parse.yaml
name: mylib_parse
family: mylib
float: false                      # true -> KLEE-Float container
sources: [benchmarks/mylib/src/*.c]
harness: benchmarks/mylib/klee_harness.c      # a main() that makes the input symbolic (omit if the program has one)
include_dirs: [benchmarks/mylib/include, benchmarks]   # `benchmarks` provides klee_extra.h
defines: [HAVE_CONFIG_H=1]
coverage_files: [benchmarks/mylib/src/parse.c]        # what to report coverage on
entry_function: mylib_parse
libc: uclibc
posix_runtime: true
notes: "what the input is, what the entry does (shown to the LLM)"
```

Everything under the project root is visible in the containers at the same
relative path (`/gordian/...`).  A single `.c` file with its own KLEE `main()`
can be passed to `gordian run` directly.

## 7. Getting the most coverage out of a run

* **Prefer an agent backend** (Claude Code or Codex) for large programs: it
  compiles and tests its ghost code, repairs compile errors, and edits large
  files in place.  API backends work well on small programs.
* **Give it time**: 600 s is enough for a logic bomb, 900 s for an FDLibM
  function, 1500–3600 s for a parser.  LLM calls count against the budget, and
  each KLEE run of a ghost variant is guaranteed at least 5 % of it.
* **Let the feedback rounds run**: the partition and model stages make a
  second attempt with the still-uncovered lines and KLEE's diagnostics.
* **Read `report.md`**: a stubborn region can be re-run with
  `--stages inversion` or `--stages rewrite` and a larger budget.
* **Who picks the technique**: with the default option, the three ghost-code stages run in a
  fixed order (partition, model, inversion) and the LLM's triage only routes
  regions within the last two.  `--stages auto` lets the triage choose the
  order (summed scores per technique; techniques it routed nothing to run last
  with the leftover budget); the chosen order is recorded as `stage_order` in
  `report.json`.
* **Prompt context**: the prompts show the whole annotated file by default
  (`--context file`).  `--context slice` shows only the file preamble, the
  functions enclosing the target, their direct callees and `main`; omitted
  ranges are marked and expanded back when the LLM returns a copy of the file.

## 8. Layout

```
gordian/            the package: config, docker, klee, coverage, targets, llm/, stages/, pipeline, cli
docker/             Dockerfiles for the two KLEE backends
benchmarks/         programs and harnesses; benchmarks/targets/ holds the target specs
scripts/            result summariser for your own runs
tests/              unit tests (`pytest`)
runs/               one directory per run (created on demand)
```
