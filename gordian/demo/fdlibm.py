"""The small FDLibM dependency closure and its reproducible source snapshot."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


SOURCES = (
    "s_sin.c", "s_cos.c", "k_sin.c", "k_cos.c",
    "e_rem_pio2.c", "k_rem_pio2.c",
    "s_fabs.c", "s_floor.c", "s_scalbn.c", "s_copysign.c",
)
SYMBOLS = (
    "sin", "cos", "__kernel_sin", "__kernel_cos",
    "__ieee754_rem_pio2", "__kernel_rem_pio2",
    "fabs", "floor", "scalbn", "copysign",
)


def source_paths(directory: Path) -> list[Path]:
    return [directory / name for name in SOURCES]


def compile_flags() -> list[str]:
    """Use the same arithmetic, word layout and symbol bindings in both builds."""
    return ["-std=c11", "-fno-builtin", "-fno-strict-aliasing", "-ffp-contract=off",
            "-D__LITTLE_ENDIAN"] + [f"-D{name}=gordian_fdlibm_{name}" for name in SYMBOLS]


def snapshot_sources(source: Path, destination: Path) -> dict:
    """Copy exact repository bytes, including notices, before either build starts."""
    files = {name: (source / name).read_bytes() for name in (*SOURCES, "fdlibm.h")}
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        (destination / name).write_bytes(data)
    manifest = dict(source=str(source), sources=list(SOURCES), compile_flags=compile_flags(),
                    sha256={name: hashlib.sha256(data).hexdigest() for name, data in files.items()})
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
