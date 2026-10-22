from gordian.ktest import read_ktest, write_ktest


def test_roundtrip(tmp_path):
    objs = [{"name": "s", "size": 3, "bytes": b"abc"}, {"name": "n", "size": 4, "bytes": b"\x01\x00\x00\x00"}]
    p = tmp_path / "t.ktest"
    write_ktest(p, objs)
    back = read_ktest(p)
    assert [(o["name"], o["bytes"]) for o in back] == [("s", b"abc"), ("n", b"\x01\x00\x00\x00")]
