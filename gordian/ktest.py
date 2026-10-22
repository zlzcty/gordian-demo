"""Pure-python reader/writer for KLEE .ktest files (format version 3/4)."""
from __future__ import annotations

import struct
from pathlib import Path


def read_ktest(path: Path) -> list[dict]:
    data = Path(path).read_bytes()
    if data[:5] not in (b"KTEST", b"BOUT\n"):
        raise ValueError(f"{path}: not a ktest file")
    pos = 5
    (version,) = struct.unpack(">i", data[pos:pos + 4]); pos += 4
    if version > 4:
        raise ValueError(f"{path}: unsupported ktest version {version}")
    (numargs,) = struct.unpack(">i", data[pos:pos + 4]); pos += 4
    args = []
    for _ in range(numargs):
        (n,) = struct.unpack(">i", data[pos:pos + 4]); pos += 4
        args.append(data[pos:pos + n].decode(errors="replace")); pos += n
    if version >= 2:
        pos += 8  # symArgvs, symArgvLen
    (numobjs,) = struct.unpack(">i", data[pos:pos + 4]); pos += 4
    objs = []
    for _ in range(numobjs):
        (n,) = struct.unpack(">i", data[pos:pos + 4]); pos += 4
        name = data[pos:pos + n].decode(errors="replace"); pos += n
        (m,) = struct.unpack(">i", data[pos:pos + 4]); pos += 4
        objs.append({"name": name, "size": m, "bytes": data[pos:pos + m]}); pos += m
    return objs


def write_ktest(path: Path, objects: list[dict], args: list[str] | None = None) -> None:
    args = args or ["prog"]
    out = bytearray(b"KTEST")
    out += struct.pack(">i", 3)
    out += struct.pack(">i", len(args))
    for a in args:
        b = a.encode()
        out += struct.pack(">i", len(b)) + b
    out += struct.pack(">ii", 0, 0)
    out += struct.pack(">i", len(objects))
    for o in objects:
        name = o["name"].encode()
        out += struct.pack(">i", len(name)) + name
        out += struct.pack(">i", len(o["bytes"])) + bytes(o["bytes"])
    Path(path).write_bytes(out)


def ktest_as_json(path: Path) -> dict:
    objs = read_ktest(path)
    return {"file": str(path), "objects": [{"name": o["name"], "size": o["size"], "hex": o["bytes"].hex()} for o in objs]}
