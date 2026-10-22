"""Generate target specs for the benchmark families shipped under ``benchmarks/``.

``gordian bench init`` writes one YAML per target into ``benchmarks/targets/``.
A new benchmark is added by writing such a YAML by hand (see ``targets.py``);
nothing here is required for that.
"""
from __future__ import annotations

import re
from pathlib import Path

from .targets import Target
from .log import get_logger

log = get_logger(__name__)

LOGIC_BOMB_LIBS = ["benchmarks/lib/utils.c", "benchmarks/lib/sha1.c", "benchmarks/lib/aes.c", "benchmarks/lib/crypto_utils.c"]

BC_DEFINES = ["VERSION=7.1.0", "BC_ENABLED=1", "DC_ENABLED=1", "BUILD_TYPE=A", "EXECPREFIX=", "MAINEXEC=bc",
              "BC_NUM_KARATSUBA_LEN=32", "BC_ENABLE_NLS=0", "BC_ENABLE_EXTRA_MATH=1", "BC_ENABLE_HISTORY=1",
              "BC_ENABLE_LIBRARY=0", "BC_ENABLE_MEMCHECK=0", "BC_ENABLE_AFL=0", "BC_ENABLE_OSSFUZZ=0",
              "_POSIX_C_SOURCE=200809L", "_XOPEN_SOURCE=700"]
BC_COVERAGE = ["num.c", "lex.c", "parse.c", "bc_parse.c", "program.c", "read.c", "vm.c"]
JQ_SOURCES = ["jv", "jv_parse", "jv_dtoa", "jv_dtoa_tsd", "jv_alloc", "jv_unicode", "jv_aux", "jv_print", "util",
              "execute", "jv_file", "locfile", "linker", "parser", "lexer", "compile", "bytecode", "builtin"]
JQ_COVERAGE = ["jv.c", "jv_alloc.c", "jv_aux.c", "jv_parse.c", "jv_unicode.c"]
EXPAT_COVERAGE = ["xmlparse.c", "xmlrole.c", "xmltok.c", "xmltok_impl.c", "xmltok_ns.c"]


def _uses_float(text: str) -> bool:
    return bool(re.search(r"\b(double|float)\b", text)) and "asm" not in text


def logic_bomb_targets(root: Path) -> list[Target]:
    out = []
    src_root = root / "benchmarks/logic_bombs_src"
    for f in sorted(src_root.glob("*/*_klee.c")):
        if f.parent.name == "experiments":
            continue
        rel = f.relative_to(root).as_posix()
        text = f.read_text(errors="replace")
        out.append(Target(
            name=f"lb_{f.stem.replace('_klee', '')}", family="logic_bombs", float=_uses_float(text),
            sources=[rel] + LOGIC_BOMB_LIBS, include_dirs=["benchmarks/include", "benchmarks"],
            coverage_files=[rel], entry_function="logic_bomb", libc="uclibc", posix_runtime=True,
            notes=f"LogicBombs benchmark, category {f.parent.name}. The bomb is reached when klee_assert(0) / BOMB_ENDING is hit."))
    return out


def fdlibm_targets(root: Path) -> list[Target]:
    out = []
    lib = root / "benchmarks/fdlibm_lib"
    # fdlibm_blacklist.txt lists files that are not standalone *benchmarks*; they are still part of the library.
    lib_sources = sorted(p.name for p in lib.glob("*.c") if p.name != "driver.c")
    for d in sorted((root / "benchmarks/fdlibm").iterdir()):
        if not d.is_dir():
            continue
        main = d / f"{d.name}_main_annotated_no_models.c"
        if not main.exists():
            main = d / f"{d.name}_main.c"
        if not main.exists():
            continue
        others = [f"benchmarks/fdlibm_lib/{s}" for s in lib_sources if s != f"{d.name}.c"]
        rel = main.relative_to(root).as_posix()
        out.append(Target(
            # The original evaluation ran the floating-point instances (FDLibM, float logic bombs) on
            # KLEE-Float.  The distributed tool defaults to standard KLEE 3.0 for them because the
            # KLEE-Float fork (LLVM 3.4, 2017) crashes on many of these programs (CexCachingSolver
            # assertion on external sin/cos calls) and has no coverage tooling.  `--float` on
            # `gordian run`/`explore`, or `float: true` in the target spec, switches back to KLEE-Float.
            name=f"fdlibm_{d.name}", family="fdlibm", float=False,
            sources=[rel] + others, include_dirs=[f"benchmarks/fdlibm/{d.name}", "benchmarks/fdlibm_lib"],
            coverage_files=[rel], entry_function=f"__ieee754_{d.name[2:]}" if d.name.startswith("e_") else d.name,
            libc="none", posix_runtime=False, link_flags=["-lm"],
            notes="FDLibM math routine with a KLEE main() that makes the double inputs symbolic. "
                  "Bit-level access via __HI/__LO macros on IEEE-754 representation."))
    return out


def bc_targets(root: Path) -> list[Target]:
    srcs = [f"benchmarks/bc/src/{p.name}" for p in sorted((root / "benchmarks/bc/src").glob("*.c")) if "fuzzer" not in p.name]
    srcs += [f"benchmarks/bc/gen/{p.name}" for p in sorted((root / "benchmarks/bc/gen").glob("*.c")) if p.name != "strgen.c"]
    return [Target(
        name=f"bc_{Path(c).stem}", family="bc", float=False, sources=srcs,
        harness="benchmarks/bc_benchmarks/bc_harness_klee.c",
        include_dirs=["benchmarks/bc/include", "benchmarks"], defines=BC_DEFINES,
        cflags=["-g0"],   # KLEE 3.0's module verifier rejects bc's debug info ("inlinable call ... must have a !dbg location")
        coverage_files=[f"benchmarks/bc/src/{c}"], entry_function="real_main",
        notes="bc (POSIX calculator language; Gavin D. Howard's bc with the GNU bc extensions, referred to as "
              "'GNU bc' for simplicity). The harness builds argv {bc,-e,<expr>} with a symbolic expression "
              "and calls real_main. Input is a bc program text.") for c in BC_COVERAGE]


def jq_targets(root: Path) -> list[Target]:
    srcs = [f"benchmarks/jq/src/{s}.c" for s in JQ_SOURCES]
    return [Target(
        name=f"jq_{Path(c).stem}", family="jq", float=False, sources=srcs,
        harness="benchmarks/jq_benchmarks/jq_klee_harness.c",
        include_dirs=["benchmarks/jq", "benchmarks/jq/src", "benchmarks"], defines=["IEEE_8087", "_POSIX_C_SOURCE=200809L"],
        coverage_files=[f"benchmarks/jq/src/{c}"], entry_function="jv_parse", link_flags=["-lm"],
        notes="jq JSON processor. The harness parses a symbolic JSON text with jv_parse.") for c in JQ_COVERAGE]


def libexpat_targets(root: Path) -> list[Target]:
    srcs = [f"benchmarks/libexpat/expat/lib/{s}" for s in ("xmlparse.c", "xmltok.c", "xmlrole.c")]
    return [Target(
        name=f"libexpat_{Path(c).stem}", family="libexpat", float=False, sources=srcs,
        harness="benchmarks/libexpat_benchmarks/xml_klee_harness.c",
        include_dirs=["benchmarks/libexpat/expat/lib", "benchmarks/libexpat", "benchmarks/libexpat/build", "benchmarks"],
        coverage_files=[f"benchmarks/libexpat/expat/lib/{c}"], entry_function="XML_Parse",
        notes="libexpat XML parser. The harness feeds a symbolic buffer to XML_Parse.") for c in EXPAT_COVERAGE]


def libyaml_targets(root: Path) -> list[Target]:
    base = ["benchmarks/libyaml/src/api.c", "benchmarks/libyaml/src/reader.c", "benchmarks/libyaml/src/scanner.c",
            "benchmarks/libyaml/klee/libyaml_klee_compat.c"]
    common = dict(family="libyaml", float=False, defines=["HAVE_CONFIG_H=1", "YAML_DECLARE_STATIC=1"],
                  include_dirs=["benchmarks/libyaml/include", "benchmarks/libyaml/klee/gordian_build/include", "benchmarks"],
                  klee_args=["--only-output-states-covering-new"],
                  notes="libyaml YAML parser. The harness feeds a symbolic 256-byte document to the parser/scanner.")
    return [
        Target(name="libyaml_parser", sources=base + ["benchmarks/libyaml/src/parser.c"],
               harness="benchmarks/libyaml/klee/libyaml_parser_harness.c",
               coverage_files=["benchmarks/libyaml/src/parser.c"], entry_function="yaml_parser_parse", **common),
        Target(name="libyaml_scanner", sources=base,
               harness="benchmarks/libyaml/klee/libyaml_scanner_harness.c",
               coverage_files=["benchmarks/libyaml/src/scanner.c"], entry_function="yaml_parser_scan", **common),
    ]


FAMILIES = {"logic_bombs": logic_bomb_targets, "fdlibm": fdlibm_targets, "bc": bc_targets, "jq": jq_targets,
            "libexpat": libexpat_targets, "libyaml": libyaml_targets}


def init_targets(root: Path, families: list[str] | None = None) -> list[Target]:
    out_dir = root / "benchmarks/targets"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for fam, fn in FAMILIES.items():
        if families and fam not in families:
            continue
        try:
            targets = fn(root)
        except FileNotFoundError as exc:
            log.warning("skipping family %s: %s", fam, exc)
            continue
        for t in targets:
            t.save(out_dir / f"{t.name}.yaml")
            written.append(t)
        log.info("family %s: %d targets", fam, len(targets))
    return written
