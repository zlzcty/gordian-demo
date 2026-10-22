import struct

import pytest
import z3

from gordian.stages.opt import opt_closest


def closest(ctype, target, candidates):
    fmt = "<f" if ctype == "float" else "<d"
    size = struct.calcsize(fmt)
    arr = z3.Array("x", z3.BitVecSort(32), z3.BitVecSort(8))
    bits = z3.Concat(*[z3.Select(arr, z3.BitVecVal(i, 32)) for i in reversed(range(size))])
    choices = [struct.pack(fmt, x) for x in candidates]
    hard = [z3.Or(*[bits == z3.BitVecVal(int.from_bytes(x, "little"), size * 8) for x in choices])]
    result = opt_closest(hard, {"x": arr}, {"x": size},
                         {"x": struct.pack(fmt, target)}, numeric=("x", ctype))
    if result is None:
        return None
    assert result["x"] in choices
    return struct.unpack(fmt, result["x"])[0]


@pytest.mark.parametrize("ctype", ["float", "double"])
@pytest.mark.parametrize("target,candidates,expected", [
    (1.0, [3.0, -0.1], -0.1),
    (-1.0, [-3.0, 0.1], 0.1),
    (1.0, [0.5, 1.75], 0.5),
    (0.0, [-0.0, 1.0], -0.0),
    (1.0, [float("nan"), float("inf"), -float("inf"), 2.0], 2.0),
])
def test_float_numeric_distance(ctype, target, candidates, expected):
    fmt = "<f" if ctype == "float" else "<d"
    assert closest(ctype, target, candidates) == struct.unpack(fmt, struct.pack(fmt, expected))[0]


@pytest.mark.parametrize("ctype,smallest", [("float", 2.0 ** -149), ("double", 2.0 ** -1074)])
def test_subnormal_distance(ctype, smallest):
    assert closest(ctype, 0.0, [-smallest, 1.0]) == -smallest


@pytest.mark.parametrize("ctype", ["float", "double"])
@pytest.mark.parametrize("target", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_target_has_no_numeric_optimum(ctype, target):
    assert closest(ctype, target, [1.0, 2.0]) is None


@pytest.mark.parametrize("ctype", ["float", "double"])
def test_only_nonfinite_candidates(ctype):
    assert closest(ctype, 1.0, [float("nan"), float("inf"), -float("inf")]) is None


@pytest.mark.parametrize("ctype,size,fmt,sort", [
    ("float", 4, "<f", z3.Float32()),
    ("double", 8, "<d", z3.Float64()),
])
@pytest.mark.parametrize("bounded", [False, True])
def test_numeric_distance_over_symbolic_range(ctype, size, fmt, sort, bounded):
    arr = z3.Array("x", z3.BitVecSort(32), z3.BitVecSort(8))
    bits = z3.Concat(*[z3.Select(arr, z3.BitVecVal(i, 32)) for i in reversed(range(size))])
    value = z3.fpBVToFP(bits, sort)
    hard = [z3.fpGEQ(value, z3.FPVal(2, sort)), z3.fpLEQ(value, z3.FPVal(4, sort))] if bounded else []
    result = opt_closest(hard, {"x": arr}, {"x": size}, {"x": struct.pack(fmt, 1.0)},
                         numeric=("x", ctype), timeout_ms=3000)
    assert result is not None
    assert struct.unpack(fmt, result["x"])[0] == (2.0 if bounded else 1.0)


@pytest.mark.parametrize("ctype,largest", [
    ("float", float.fromhex("0x1.fffffep+127")),
    ("double", float.fromhex("0x1.fffffffffffffp+1023")),
])
def test_large_numeric_distance_does_not_overflow(ctype, largest):
    assert closest(ctype, -largest, [largest, 0.0]) == 0.0
