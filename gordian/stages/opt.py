"""The OPT step of the bidirectional propagation algorithm, done exactly:

    A = OPT(dist(targets, sigma), pi)

with Z3's optimization engine.  ``pi`` is the path condition KLEE wrote for the test case
(``--write-smt2s``), split into the prefix part (only original inputs) and the suffix part (mentions
the havoc variables ``ghost_*``).  For a single numeric interface variable the objective is the
l1 distance |A(x) - sigma(x)| on its numeric value for finite floats and its bit-vector value
for integers; for several variables the soft equalities
``x_i == sigma(x_i)`` (one per byte) form a partial MaxSAT instance, which is what ``Optimize.add_soft``
solves.
"""
from __future__ import annotations

import struct
from fractions import Fraction
from pathlib import Path
from time import monotonic
from typing import Optional

import z3

from ..log import get_logger

log = get_logger(__name__)


def load_path_condition(smt2_path: Path) -> tuple[list[z3.BoolRef], dict[str, z3.ArrayRef]]:
    """Parse a KLEE .smt2 file -> (list of top-level conjuncts, {array name: z3 array const})."""
    text = smt2_path.read_text(errors="replace")
    text = text.replace("(check-sat)", "").replace("(exit)", "")
    av = z3.parse_smt2_string(text)
    conjs: list[z3.BoolRef] = []
    stack = list(av)
    while stack:
        e = stack.pop()
        if z3.is_and(e):
            stack.extend(e.children())
        else:
            conjs.append(e)
    arrays: dict[str, z3.ArrayRef] = {}
    for c in conjs:
        for a in _array_consts(c):
            arrays[a.decl().name()] = a
    return conjs, arrays


def _array_consts(expr) -> list:
    out, seen, stack = [], set(), [expr]
    while stack:
        e = stack.pop()
        if e.get_id() in seen:
            continue
        seen.add(e.get_id())
        if not z3.is_expr(e):
            continue
        if z3.is_const(e) and z3.is_array(e):
            out.append(e)
        stack.extend(e.children())
    return out


def split_pre_suf(conjs: list[z3.BoolRef], ghost_prefix: str = "ghost_") -> tuple[list, list]:
    pre, suf = [], []
    for c in conjs:
        names = {a.decl().name() for a in _array_consts(c)}
        (suf if any(n.startswith(ghost_prefix) for n in names) else pre).append(c)
    return pre, suf


def _bv_of(arr: z3.ArrayRef, size: int) -> z3.BitVecRef:
    bv = z3.Select(arr, z3.BitVecVal(0, 32))
    for i in range(1, size):
        bv = z3.Concat(z3.Select(arr, z3.BitVecVal(i, 32)), bv)   # little endian
    return bv


def _model_bytes(m: z3.ModelRef, arr: z3.ArrayRef, size: int) -> bytes:
    out = bytearray()
    for i in range(size):
        v = m.eval(z3.Select(arr, z3.BitVecVal(i, 32)), model_completion=True)
        out.append(v.as_long() & 0xFF)
    return bytes(out)


def _closest_float(o, arrays, sizes, targets, name, ctype, timeout_ms):
    size = 4 if ctype == "float" else 8
    if sizes[name] != size or len(targets[name]) != size:
        return None
    width = size * 8
    fraction_bits, exponent_bits = (23, 8) if size == 4 else (52, 11)
    exponent_mask = ((1 << exponent_bits) - 1) << fraction_bits
    target_bits = int.from_bytes(targets[name], "little")
    if target_bits & exponent_mask == exponent_mask:
        return None
    sign_mask = 1 << (width - 1)
    full_mask = (1 << width) - 1
    target_key = (~target_bits & full_mask) if target_bits & sign_mask else target_bits ^ sign_mask
    bv = _bv_of(arrays[name], size)
    key = z3.If((bv & sign_mask) != 0, ~bv, bv ^ sign_mask)
    o.add((bv & exponent_mask) != exponent_mask)
    fmt = "<f" if size == 4 else "<d"
    target = Fraction(struct.unpack(fmt, targets[name])[0])
    deadline = monotonic() + timeout_ms / 1000 if timeout_ms else None
    best, best_distance = None, None
    for below in (True, False):
        if deadline is not None:
            remaining = int((deadline - monotonic()) * 1000)
            if remaining <= 0:
                return None
            o.set("timeout", remaining)
        o.push()
        o.add(z3.ULE(key, target_key) if below else z3.UGE(key, target_key))
        o.minimize(target_key - key if below else key - target_key)
        result = o.check()
        if result == z3.unknown:
            log.debug("OPT: %s", result)
            return None
        if result == z3.sat:
            model = o.model()
            candidate = {n: _model_bytes(model, arr, sizes.get(n, 1)) for n, arr in arrays.items()}
            distance = abs(Fraction(struct.unpack(fmt, candidate[name])[0]) - target)
            if best_distance is None or distance < best_distance:
                best, best_distance = candidate, distance
            if distance == 0:
                return best
        o.pop()
    return best


def opt_closest(hard: list[z3.BoolRef], arrays: dict[str, z3.ArrayRef], sizes: dict[str, int],
                targets: dict[str, bytes], numeric: Optional[tuple[str, str]] = None,
                timeout_ms: int = 20000) -> Optional[dict[str, bytes]]:
    """Assignment satisfying ``hard`` that is closest to ``targets`` (name -> bytes).

    ``numeric=(name, ctype)`` selects the l1 objective on finite floating-point values
    or integer bit-vector values; otherwise soft byte equalities (partial MaxSAT).
    Non-finite floating-point targets or no finite satisfying assignment return None.
    Returns bytes for every array in ``arrays``.
    """
    o = z3.Optimize()
    o.set("timeout", timeout_ms)
    for h in hard:
        o.add(h)
    if numeric and numeric[0] in arrays and numeric[0] in targets:
        name, ctype = numeric
        size = sizes[name]
        bv = _bv_of(arrays[name], size)
        v = z3.BitVecVal(int.from_bytes(targets[name], "little"), size * 8)
        if ctype in ("float", "double"):
            return _closest_float(o, arrays, sizes, targets, name, ctype, timeout_ms)
        else:
            signed = ctype in ("int", "long", "long long", "short", "char", "signed char") or ctype.startswith("int")
            if signed:
                dist = z3.If(bv >= v, bv - v, v - bv)
            else:
                dist = z3.If(z3.UGE(bv, v), bv - v, v - bv)
        o.minimize(dist)
    else:
        for name, b in targets.items():
            if name not in arrays:
                continue
            for i, byte in enumerate(b[:sizes.get(name, len(b))]):
                o.add_soft(z3.Select(arrays[name], z3.BitVecVal(i, 32)) == z3.BitVecVal(byte, 8), weight=1)
    r = o.check()
    if r != z3.sat:
        log.debug("OPT: %s", r)
        return None
    m = o.model()
    return {name: _model_bytes(m, arr, sizes.get(name, 1)) for name, arr in arrays.items()}


def value_to_bytes(v, ctype: str, size: int) -> Optional[bytes]:
    """Encode a forward.py result (number or hex string) as the C object's bytes."""
    try:
        if isinstance(v, str):
            b = bytes.fromhex(v)
            return b if len(b) == size else None
        if ctype == "float" and size == 4:
            return struct.pack("<f", float(v))
        if ctype == "double" and size == 8:
            return struct.pack("<d", float(v))
        iv = int(v)
        signed = not ("unsigned" in ctype or ctype.startswith("uint"))
        return iv.to_bytes(size, "little", signed=signed)
    except (ValueError, OverflowError, struct.error):
        return None
