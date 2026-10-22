from pathlib import Path

from gordian.stages.common import annotate_source, group_uncovered, rank_regions
from gordian.stages.inversion import _symbolic_decls, _inject_assumes, _assume_lines
from gordian.coverage import _line_counts, _main_range

SRC = """#include <klee/klee.h>
int logic_bomb(char *s) {
    double x = s[0];
    if (x > 1) return 1;
    return 0;
}
int main() {
    char s[5];
    double d;
    klee_make_symbolic(&s, sizeof(s), "s");
    klee_make_symbolic(&d, sizeof(d), "d");
    return logic_bomb(s);
}
"""


def test_annotate_and_regions(tmp_path: Path):
    p = tmp_path / "a.c"
    p.write_text(SRC)
    out = annotate_source(p, {4, 5})
    assert "UNCOVERED" in out.splitlines()[3] and "UNCOVERED" not in out.splitlines()[2]
    regions = group_uncovered([(4, "a"), (5, "b"), (9, "c")])
    assert regions == [(4, 5), (9, 9)]
    assert rank_regions(regions, {4, 5, 9})[0] == (4, 5)


def test_main_range():
    assert _main_range(SRC.splitlines()) == (7, 13)


def test_symbolic_decls_and_assumes():
    decls = _symbolic_decls(SRC)
    assert decls["s"]["is_array"] and decls["d"]["ctype"] == "double"
    assert _assume_lines(decls["d"], "d", (2.5).to_bytes(8, "little") if False else __import__("struct").pack("<d", 2.5), 0.0) == [
        "klee_assume(d >= 2.5);", "klee_assume(d <= 2.5);"]
    code = _inject_assumes(SRC, decls, {"s": b"ab\x00\x00\x00"}, 0.0)
    assert "klee_assume(s[0] == 97);" in code and code.index("klee_assume(s[0]") > code.index('"s"')


def test_line_counts_braceless_branch_not_covered():
    # clang-18 segments for `if (x == 14)\n    return 1;\n else\n    return 0;` (lines 4-7), benign path only:
    # the non-entry segment resuming at (5, 17) after `return 1;` must not mark line 5 covered.
    segs = [[2, 23, 1, True, True, False], [4, 9, 1, True, True, False], [4, 16, 1, True, False, False],
            [4, 17, 0, True, False, True], [5, 9, 0, True, True, False], [5, 17, 1, True, False, False],
            [7, 9, 1, True, True, False], [7, 17, 1, True, False, False], [8, 2, 0, False, False, False]]
    counts = _line_counts(segs)
    assert counts[5] == 0
    assert all(counts[ln] == 1 for ln in (2, 3, 4, 6, 7, 8))


SLICE_SRC = """#include <klee/klee.h>
#define N 4
static int helper(int v) {
    return v * 3;
}
int unused(int q) {
    return q;
}
int logic_bomb(char *s) {
    int x = helper(s[0]);
    if (x == 42)
        return 1;
    return 0;
}
int main() {
    char s[N];
    klee_make_symbolic(&s, sizeof(s), "s");
    return logic_bomb(s);
}
"""


def test_slice_lines_and_restore(tmp_path: Path):
    from gordian.stages.common import function_ranges, slice_lines, annotate_source, restore_omitted
    p = tmp_path / "b.c"
    p.write_text(SLICE_SRC)
    lines = SLICE_SRC.splitlines()
    names = [n for n, _, _ in function_ranges(lines)]
    assert names == ["helper", "unused", "logic_bomb", "main"]
    keep = slice_lines(p, {12})          # `return 1;` inside logic_bomb (lines 9-14)
    assert {1, 2} <= keep                # preamble
    assert all(ln in keep for ln in range(9, 15))    # enclosing function
    assert all(ln in keep for ln in range(3, 6))     # callee helper()
    assert all(ln in keep for ln in range(15, 20))   # main
    assert not any(ln in keep for ln in range(6, 9)) # unused() is dropped
    listing = annotate_source(p, {12}, number=False, keep=keep)
    assert "/* ... lines 6-8 omitted ... */" in listing and "UNCOVERED" in listing
    restored = restore_omitted(listing.replace(" /* UNCOVERED */", ""), lines)
    assert restored.splitlines() == lines


def test_auto_stage_order():
    from gordian.pipeline import auto_stage_order
    triage = [{"technique": "inversion", "score": 0.8}, {"technique": "model", "score": 0.5},
              {"technique": "inversion", "score": 0.3}, {"technique": "none", "score": 0.9}]
    assert auto_stage_order(triage) == ["inversion", "rewrite", "partition"]
    assert auto_stage_order([]) == ["partition", "rewrite", "inversion"]


def test_target_markers_on_windowed_listing(tmp_path: Path):
    # a listing windowed around the focus (file > max_chars) must still get TARGET markers by original line number
    from gordian.stages.common import annotate_source
    from gordian.stages.inversion import _expand_to_file_lines, _collapse_file_lines
    lines = [f"int v{i} = {i};" for i in range(1, 401)]
    p = tmp_path / "big.c"
    p.write_text("\n".join(lines) + "\n")
    listing = annotate_source(p, {300}, number=False, max_chars=100, focus={300}, context=5)
    ann = _expand_to_file_lines(listing.splitlines(), len(lines))
    assert ann[299].startswith("int v300 = 300;") and ann[0] is None
    ann[299] += " /* TARGET */"
    out = _collapse_file_lines(ann)
    assert out[0] == "/* ... lines 1-294 omitted ... */" and "int v300 = 300; /* UNCOVERED */ /* TARGET */" in out
    assert out[-1] == "/* ... lines 306-400 omitted ... */"


def test_bomb_and_benign_lines():
    from gordian.cli import bomb_and_benign_lines
    named = ["#define BOMB_ENDING 1", "int f(int x) {", "    if (x == 7)", "        return BOMB_ENDING;", "    return NORMAL_ENDING;", "}"]
    assert bomb_and_benign_lines(named) == ({4}, {5})
    plain = ["int f(int j) {", "    if (j == 7) {", "        return 1;", "    } else {", "        return 0;", "    }", "}"]
    assert bomb_and_benign_lines(plain) == ({3}, {5})
    assert bomb_and_benign_lines(["void g(void) {", "    klee_assert(0 && \"bomb\");", "}"]) == ({2}, set())
