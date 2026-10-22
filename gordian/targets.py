"""Target specifications: what program to analyse and how to build it.

A *target* is a YAML file (``benchmarks/targets/<name>.yaml`` or anywhere) that
describes one program under test.  Gordian never guesses a benchmark family
from path substrings; everything it needs is in the spec.

    name: bc_num
    family: bc                      # free-form tag, used for grouping/reporting only
    float: false                    # run KLEE-Float instead of standard KLEE
    sources:                        # C files compiled and linked into the KLEE module
      - benchmarks/bc/src/*.c       #   (globs allowed, relative to project root)
    harness: benchmarks/bc_benchmarks/bc_harness_klee.c   # optional separate main()
    include_dirs: [benchmarks/bc/include]
    defines: [BC_ENABLED=1]
    cflags: []                      # extra clang flags for bitcode AND replay builds
    link_flags: [-lm]               # extra native link flags for the replay binary
    coverage_files: [benchmarks/bc/src/num.c]   # files whose line coverage is reported
    entry_function: real_main       # the function the harness drives (for prompts)
    libc: uclibc                    # uclibc | none
    posix_runtime: true
    klee_args: []                   # extra klee options
    external_calls: all             # klee --external-calls
    notes: ""                       # free text shown to the LLM

For a single-file program whose main() already calls klee_make_symbolic
(the LogicBombs and FDLibM harnesses), ``sources`` is that file and there is
no ``harness``.
"""
from __future__ import annotations

import glob
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class Target:
    name: str
    sources: list[str]
    family: str = "custom"
    float: bool = False
    harness: Optional[str] = None
    include_dirs: list[str] = field(default_factory=list)
    defines: list[str] = field(default_factory=list)
    cflags: list[str] = field(default_factory=list)
    link_flags: list[str] = field(default_factory=list)
    coverage_files: list[str] = field(default_factory=list)
    entry_function: str = "main"
    libc: str = "uclibc"
    posix_runtime: bool = True
    klee_args: list[str] = field(default_factory=list)
    external_calls: str = "all"
    symbolic_input_names: list[str] = field(default_factory=list)   # informational
    notes: str = ""
    spec_path: Optional[str] = None

    # ---- resolution -----------------------------------------------------------
    def resolve_sources(self, root: Path) -> list[Path]:
        out: list[Path] = []
        for pat in self.sources:
            p = root / pat
            matches = sorted(Path(m) for m in glob.glob(str(p))) if any(ch in pat for ch in "*?[") else [p]
            if not matches:
                raise FileNotFoundError(f"target {self.name}: no sources match {pat}")
            out.extend(m for m in matches if m.suffix in (".c", ".bc", ".ll"))
        return out

    def resolve_coverage_files(self, root: Path) -> list[Path]:
        if self.coverage_files:
            return [root / c for c in self.coverage_files]
        srcs = [s for s in self.resolve_sources(root) if s.suffix == ".c"]
        return srcs

    def harness_path(self, root: Path) -> Optional[Path]:
        return root / self.harness if self.harness else None

    def primary_source(self, root: Path) -> Path:
        """The file an LLM should look at first: first coverage file, else first source."""
        cov = self.resolve_coverage_files(root)
        return cov[0] if cov else self.resolve_sources(root)[0]

    def clang_flags(self, root: Path, container_path) -> list[str]:
        flags = ["-I" + container_path(root / d) for d in self.include_dirs]
        flags += ["-D" + d for d in self.defines]
        flags += list(self.cflags)
        return flags

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("spec_path", None)
        return d

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(self.as_dict(), sort_keys=False))
        self.spec_path = str(path)


def load_target(path: Path) -> Target:
    data = yaml.safe_load(Path(path).read_text())
    t = Target(**data)
    t.spec_path = str(path)
    return t


def find_target(root: Path, name_or_path: str) -> Target:
    p = Path(name_or_path)
    if p.suffix in (".yaml", ".yml") and p.exists():
        return load_target(p)
    cand = root / "benchmarks" / "targets" / f"{name_or_path}.yaml"
    if cand.exists():
        return load_target(cand)
    if p.suffix == ".c" and p.exists():
        return target_from_c_file(root, p)
    raise FileNotFoundError(f"no target named {name_or_path!r} (looked for {cand}) and it is not a .c file")


def target_from_c_file(root: Path, c_file: Path, *, float_: Optional[bool] = None, name: Optional[str] = None) -> Target:
    """Ad-hoc target for a standalone C file with its own KLEE main()."""
    c_file = c_file.resolve()
    rel = c_file.relative_to(root.resolve()).as_posix()
    text = c_file.read_text(errors="replace")
    if float_ is None:
        float_ = bool(re.search(r"\b(double|float)\b", text)) and "asm" not in text
    return Target(name=name or c_file.stem, sources=[rel], family="adhoc", float=float_,
                  include_dirs=[str(c_file.parent.relative_to(root.resolve()))], coverage_files=[rel],
                  libc="uclibc", posix_runtime=True, entry_function="main")


def list_targets(root: Path, family: Optional[str] = None) -> list[Target]:
    d = root / "benchmarks" / "targets"
    out = []
    for p in sorted(d.glob("*.yaml")) if d.exists() else []:
        t = load_target(p)
        if family is None or t.family == family:
            out.append(t)
    return out
