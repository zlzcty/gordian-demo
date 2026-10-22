from pathlib import Path

from gordian.llm.base import Backend, LLMResponse, TaskSpec, Usage, parse_file_blocks, ResponseCache


def test_parse_file_blocks_strips_fences():
    text = "intro\n<<<FILE a.c>>>\n```c\nint x;\n```\n<<<END FILE>>>\n<<<FILE sub/b.h>>>\nfoo\n<<<END FILE>>>"
    assert parse_file_blocks(text) == {"a.c": "int x;\n", "sub/b.h": "foo\n"}


class FakeBackend(Backend):
    name = "fake"
    model = "fake-1"

    def __init__(self, reply, **kw):
        super().__init__(**kw)
        self.reply = reply
        self.calls = 0

    def _complete(self, prompt, system):
        self.calls += 1
        return LLMResponse(text=self.reply, usage=Usage(input_tokens=1, output_tokens=1), model=self.model)


def test_task_emulation_writes_outputs(tmp_path: Path):
    b = FakeBackend("<<<FILE out.c>>>\nint main(void){return 0;}\n<<<END FILE>>>")
    (tmp_path / "in.c").write_text("int f;")
    res = b.run_task(TaskSpec(name="t", instructions="do it", workdir=tmp_path, inputs=["in.c"], outputs=["out.c"]))
    assert res.ok and (tmp_path / "out.c").read_text().startswith("int main")


def test_task_missing_output_is_not_ok(tmp_path: Path):
    b = FakeBackend("no files here")
    res = b.run_task(TaskSpec(name="t", instructions="do it", workdir=tmp_path, outputs=["out.c"]))
    assert not res.ok and res.missing == ["out.c"]


def test_cache_replays(tmp_path: Path):
    cache = ResponseCache(tmp_path, "fake-1")
    b = FakeBackend("hello", cache=cache)
    assert b.complete("p").text == "hello" and b.calls == 1
    assert b.complete("p").cached and b.calls == 1
