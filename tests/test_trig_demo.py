"""Demo contracts with fake network/container boundaries; no Docker or model calls."""
import json
import io
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from gordian.demo.example import (comparison, input_value, replay_outcome,
                                  surrogate_from_response)
from gordian.demo.execution import (build_original_replay, replay_test,
                                    require_prepared_container, variant_target)
from gordian.demo.fdlibm import SOURCES, SYMBOLS, compile_flags, snapshot_sources, source_paths
from gordian.demo.model import api_key, endpoint_config, request_rewrite
from gordian.demo import workflow
from gordian.ktest import read_ktest, write_ktest
from demos.trig.mock_endpoint import completion_app


def objects(value):
    return [dict(name="a0", bytes=struct.pack("<d", value), size=8)]


def response(guard="static int trig_branch(double x) { return 1; }"):
    return f"<<<FILE guard.inc>>>\n{guard}\n<<<END FILE>>>\n<<<FILE notes.md>>>\nIntervals.\n<<<END FILE>>>"


@pytest.mark.parametrize("value", [2.0, 4.0, 6.0])
def test_original_input_interface(value):
    assert input_value(objects(value)) == value


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -2.0, 1.0, 7.0])
def test_rejects_inputs_outside_original_domain(value):
    with pytest.raises(ValueError):
        input_value(objects(value))


def test_rejects_added_symbolic_inputs():
    with pytest.raises(ValueError):
        input_value(objects(2) + [dict(name="ghost_s", bytes=b"\0" * 8)])


def test_response_cannot_write_arbitrary_paths_or_replace_driver():
    assert "trig_branch" in surrogate_from_response(response())[0]
    with pytest.raises(ValueError):
        surrogate_from_response(response().replace("FILE notes.md", "FILE ../driver.c"))
    with pytest.raises(ValueError):
        surrogate_from_response(response("int main(void) { return 0; }"))
    with pytest.raises(ValueError):
        surrogate_from_response(response("static int trig_branch(double x) { klee_make_symbolic(0, 0, 0); }"))


def test_replay_requires_one_valid_observation_of_the_expected_input():
    assert replay_outcome("GORDIAN_TRIG x=4 outcome=2\n", 4) == 2
    for text in ("", "GORDIAN_TRIG x=2 outcome=1\n", "GORDIAN_TRIG x=4 outcome=0\n",
                 "GORDIAN_TRIG x=4 outcome=2\nGORDIAN_TRIG x=4 outcome=2\n"):
        with pytest.raises(ValueError):
            replay_outcome(text, 4)


def test_success_requires_both_original_outcomes_and_reports_baseline_success():
    true = dict(x=2, outcome=1)
    false = dict(x=4, outcome=2)
    assert comparison([true], [dict(error="replay failed")])["status"] == "incomplete"
    assert comparison([true], [false])["status"] == "improved"
    assert comparison([true, false], [])["status"] == "baseline_already_succeeds"


def test_endpoint_options_are_explicit():
    assert endpoint_config("openrouter", None, None) == (
        "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY_")
    assert endpoint_config("deepinfra", None, None) == (
        "https://api.deepinfra.com/v1/openai", "DEEPINFRA_API_KEY")
    assert endpoint_config("custom", "https://example.org/v1/", "MY_KEY") == (
        "https://example.org/v1", "MY_KEY")
    for url in (None, "ftp://example.org/v1", "https://secret@example.org", "https://example.org?key=secret"):
        with pytest.raises(ValueError):
            endpoint_config("custom", url, None)
    assert api_key({"MY_KEY": "secret"}, "MY_KEY") == "secret"
    with pytest.raises(ValueError, match="MY_KEY"):
        api_key({}, "MY_KEY")


def test_model_response_is_printed_and_saved(tmp_path):
    requests, emitted = [], []

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=response()))],
                               usage=None, model="vendor/model")

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    text, usage = request_rewrite(client, "vendor/model", "prompt", tmp_path, emitted.append)
    assert requests == [dict(model="vendor/model", messages=[dict(role="user", content="prompt")])]
    assert (tmp_path / "response.md").read_text() == text
    assert (tmp_path / "prompt.md").read_text() == "prompt"
    assert any(text in item for item in emitted)
    assert usage["model"] == "vendor/model"


def test_provider_error_body_is_not_echoed(tmp_path):
    def create(**kwargs):
        raise RuntimeError("sensitive provider error body")

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(RuntimeError) as error:
        request_rewrite(client, "model", "prompt", tmp_path, lambda _: None)
    assert "sensitive" not in str(error.value)


def test_unprepared_container_is_never_started():
    container = SimpleNamespace(running=lambda: False, spec=SimpleNamespace(name="klee"),
                                settings=SimpleNamespace(mount_path="/gordian"))
    with pytest.raises(RuntimeError, match="already be running"):
        require_prepared_container(container)


def test_replay_uses_fixed_original_executable_and_rejects_wrong_input(tmp_path):
    ktest = tmp_path / "candidate.ktest"
    write_ktest(ktest, objects(4))
    replay_dir = tmp_path / "replay"
    replay_dir.mkdir()
    commands = []

    def execute(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="GORDIAN_TRIG x=4 outcome=2\n", stderr="")

    container = SimpleNamespace(path=str, exec=execute)
    row = replay_test(container, tmp_path / "original-replay", ktest, replay_dir, 2)
    assert row["outcome"] == 2
    assert commands[0][-1] == str(tmp_path / "original-replay")
    assert input_value(read_ktest(replay_dir / ktest.name)) == 4
    write_ktest(ktest, objects(2))
    with pytest.raises(ValueError, match="input or branch"):
        replay_test(container, tmp_path / "original-replay", ktest, replay_dir, 2)


def test_workflow_does_not_call_model_when_baseline_succeeds(tmp_path, monkeypatch):
    container = SimpleNamespace(tools=SimpleNamespace(klee_version="fake"))
    monkeypatch.setattr(workflow, "require_prepared_container", lambda _: None)
    monkeypatch.setattr(workflow, "snapshot_sources", lambda *args: dict(sources=[]))
    monkeypatch.setattr(workflow, "build_original_replay", lambda *args: tmp_path / "original")
    monkeypatch.setattr(workflow, "observe_variant", lambda *args: dict(
        observations=[dict(x=2, outcome=1), dict(x=4, outcome=2)]))

    def unexpected_call(*args):
        pytest.fail("baseline success must not call the model")

    monkeypatch.setattr(workflow, "assist", unexpected_call)
    directory = tmp_path / "run"
    report = workflow.run_demo(container, tmp_path, directory, "driver", "guard",
                               dict(baseline_only=False), None, lambda _: None)
    assert report["status"] == "baseline_already_succeeds"
    assert json.loads((directory / "result.json").read_text())["status"] == report["status"]


def test_workflow_keeps_error_report_and_refuses_overwrite(tmp_path, monkeypatch):
    def fail(_):
        raise RuntimeError("container unavailable")

    monkeypatch.setattr(workflow, "require_prepared_container", fail)
    directory = tmp_path / "run"
    with pytest.raises(RuntimeError):
        workflow.run_demo(None, tmp_path, directory, "driver", "guard", {}, None, lambda _: None)
    assert json.loads((directory / "result.json").read_text())["status"] == "error"
    with pytest.raises(FileExistsError):
        workflow.run_demo(None, tmp_path, directory, "driver", "guard", {}, None, lambda _: None)


def test_workflow_records_interruptions(tmp_path, monkeypatch):
    def interrupt(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(workflow, "require_prepared_container", interrupt)
    directory = tmp_path / "run"
    with pytest.raises(KeyboardInterrupt):
        workflow.run_demo(None, tmp_path, directory, "driver", "guard", {}, None, lambda _: None)
    assert json.loads((directory / "result.json").read_text())["status"] == "interrupted"


def test_workflow_requires_original_replay_evidence_for_improvement(tmp_path, monkeypatch):
    container = SimpleNamespace(tools=SimpleNamespace(klee_version="fake"))
    monkeypatch.setattr(workflow, "require_prepared_container", lambda _: None)
    monkeypatch.setattr(workflow, "snapshot_sources", lambda *args: dict(sources=[]))
    monkeypatch.setattr(workflow, "build_original_replay", lambda *args: tmp_path / "original")
    monkeypatch.setattr(workflow, "observe_variant", lambda *args: dict(
        observations=[dict(x=2, outcome=1)], diagnostics="concretizing"))
    monkeypatch.setattr(workflow, "assist", lambda *args: (
        dict(observations=[dict(x=4, outcome=2)]), dict(model="fake")))
    report = workflow.run_demo(container, tmp_path, tmp_path / "run", "driver", "guard",
                               dict(baseline_only=False), None, lambda _: None)
    assert report["status"] == "improved"
    assert report["combined_witnesses"]["2"]["x"] == 4


def test_fdlibm_snapshot_preserves_exact_sources_and_records_hashes(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "snapshot"
    source.mkdir()
    for name in (*SOURCES, "fdlibm.h"):
        (source / name).write_bytes(b"/* original notice */\r\n")
    manifest = snapshot_sources(source, destination)
    for name in (*SOURCES, "fdlibm.h"):
        assert (destination / name).read_bytes() == (source / name).read_bytes()
        assert len(manifest["sha256"][name]) == 64
    (source / "s_sin.c").write_text("changed after snapshot")
    assert (destination / "s_sin.c").read_bytes() == b"/* original notice */\r\n"
    assert json.loads((destination / "manifest.json").read_text()) == manifest


def test_klee_target_links_fdlibm_and_disallows_external_fallback(tmp_path):
    library, driver = tmp_path / "fdlibm", tmp_path / "original/driver.c"
    target = variant_target(tmp_path, driver, library)
    assert target.sources == ["original/driver.c"] + [f"fdlibm/{name}" for name in SOURCES]
    assert target.include_dirs == ["fdlibm"]
    assert target.external_calls == "none"
    assert "-lm" not in target.link_flags
    assert "-D__LITTLE_ENDIAN" in target.cflags
    assert "-fno-strict-aliasing" in target.cflags
    assert "-ffp-contract=off" in target.cflags
    for symbol in SYMBOLS:
        assert f"-D{symbol}=gordian_fdlibm_{symbol}" in target.cflags


def test_native_build_links_the_same_fdlibm_snapshot_as_klee(tmp_path):
    commands = []

    def execute(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    container = SimpleNamespace(path=str, exec=execute, tools=SimpleNamespace(
        clang="clang", klee_include="/include", klee_runtest_lib="/lib"))
    library, driver = tmp_path / "fdlibm", tmp_path / "original/driver.c"
    build_original_replay(container, driver, tmp_path / "native", library)
    command = commands[0]
    assert str(driver) in command
    assert all(str(path) in command for path in source_paths(library))
    assert all(flag in command for flag in compile_flags())
    assert "-lm" not in command
    assert "-lkleeRuntest" in command


def test_mock_endpoint_is_labeled_and_returns_the_actual_file_protocol():
    fixture = Path(__file__).resolve().parents[1] / "demos/trig/mock-response.md"
    body = json.dumps(dict(model="rehearsal-mock", messages=[])).encode()
    statuses = []
    result = completion_app(fixture.read_text())(dict(
        REQUEST_METHOD="POST", PATH_INFO="/v1/chat/completions", CONTENT_LENGTH=str(len(body)),
        **{"wsgi.input": io.BytesIO(body)}), lambda status, headers: statuses.append(status))
    completion = json.loads(b"".join(result))
    text = completion["choices"][0]["message"]["content"]
    assert statuses == ["200 OK"]
    assert completion["model"] == "rehearsal-mock"
    assert "MOCK REHEARSAL" in text
    assert "trig_branch" in surrogate_from_response(text)[0]


def test_mock_endpoint_rejects_production_model_ids():
    body = json.dumps(dict(model="a-real-model")).encode()
    statuses = []
    completion_app("fixture")(dict(
        REQUEST_METHOD="POST", PATH_INFO="/v1/chat/completions", CONTENT_LENGTH=str(len(body)),
        **{"wsgi.input": io.BytesIO(body)}), lambda status, headers: statuses.append(status))
    assert statuses == ["400 Bad Request"]
