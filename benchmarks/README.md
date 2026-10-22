# Gordian Logic Bombs Workspace

This directory is the **main workspace mounted inside the Docker containers** for running Gordian and KLEE-based experiments. Almost all compilation, instrumentation, and symbolic execution for the benchmarks is performed inside this directory.

It aggregates **original benchmark sources**, **Gordian-enhanced benchmark variants**, and **all KLEE execution outputs** in a single, shared filesystem.

---

## High-Level Purpose

* Acts as the **execution root** for Docker-based runs
* Contains both **upstream benchmark code** and **Gordian-specific benchmark drivers**
* Stores **all KLEE outputs** (`klee-out-*`) produced during experiments

---

## Key Subdirectories and Roles

### Core Benchmarks (Upstream Code)

* `bc/`
  Source tree of the `bc` calculator used for compilation and baseline execution.
  This is Gavin D. Howard's `bc` (https://github.com/gavinhoward/bc, BSD-2-Clause,
  see `bc/LICENSE.md`), a POSIX `bc` that implements the GNU `bc` extensions; it is
  not the GNU project's own `bc`.  We refer to it as "GNU bc" for simplicity
  throughout the benchmark names, target notes and results, because it is used
  through the GNU-compatible `bc` language.

* `jq/`
  Original jq repository, including build system and dependencies.

* `libexpat/`
  Original libexpat repository used for XML parsing benchmarks.

* `fdlibm/`
  FDLIBM numerical benchmark sources. Each subdirectory corresponds to a single math routine. Mains to call the funcs with symbolic values for klee have been automatically added.

* `logic_bombs_src/`
  Original Logic Bomb benchmark programs, organized by category (buffer overflow, floating point, loops, etc.).Mains to call the funcs with symbolic values for klee have been automatically added.

These directories contain **unmodified or lightly wrapped upstream code** required for correct compilation and execution.

---

### Gordian-Enhanced Benchmarks
Because only a subset of the jq, bc, libexpat benchmark was analysed by gordian we also include them in:
* `bc_benchmarks/`
  Gordian-generated benchmark drivers and scripts used to improve coverage for bc (see the note on `bc/` above).

* `jq_benchmarks/`
  Gordian-generated benchmark drivers and scripts for jq.

* `libexpat_benchmarks/` / libexpat benchmark scripts
  Gordian-generated drivers targeting libexpat components.

For each source file whose coverage is improved by Gordian, **KLEE harnesses (mains)** are automatically generated and added here.

---

### KLEE Execution Outputs

* `klee-out-*` directories (e.g., `klee-out-0`, `klee-out-1`, `klee-out-2`)
  Standard KLEE output directories containing:

  * Generated test cases
  * Execution statistics
  * Coverage and path information



* `klee_exclusive_runs/`
  Stores KLEE-only baseline runs (STP, Z3, KLEE-Float) used for direct comparison with Gordian.

---

### Build and Replay Support

* `build/`, `build_replay/`
  Intermediate build artifacts and replay binaries used for coverage analysis.

* `llvm_pass/`
  Temporary build artifacts for the LLVM instrumentation pass used by Gordian.

---



## Summary

In short:

* This directory is the **shared execution root** for Gordian and baseline KLEE experiments
* It combines **original benchmark sources**, **Gordian-generated drivers**, and **all KLEE outputs**
* All coverage improvements reported for Logic Bombs, FDLIBM, bc, jq, and libexpat originate from runs executed in this workspace

This layout is optimized for **reproducibility, isolation, and traceability** of symbolic execution results inside Docker.
