"""Cross-stage contracts and evidence checks, independent of Docker/provider access."""
import io
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from gordian.demo import stages
from gordian.demo.checks import check, run_checks
from gordian.demo.cli import parser, validate_stage_args
from gordian.demo.execution import variant_target
from gordian.demo.target import (decode_input, decode_replay, load_target, parse_surrogate,
                                 snapshot_target, witnesses)
from demos.trig.mock_endpoint import completion_app

ROOT = Path(__file__).resolve().parents[1]


def sample_target(tmp_path):
    target = load_target(ROOT / 'demos/trig/target.json')
    target.update(driver='driver.c', guard='guard.inc', library='.', sources=[], headers=[], cflags=[])
    (tmp_path / 'driver.c').write_text('fixed driver')
    (tmp_path / 'guard.inc').write_text('original guard')
    path = tmp_path / 'spec.json'
    path.write_text(json.dumps(target))
    return path, target


def fixture_response():
    return (ROOT / 'demos/trig/mock-response.md').read_text()


def saved_stage(tmp_path, stage='baseline'):
    spec, _ = sample_target(tmp_path)
    source = tmp_path / 'before'
    source.mkdir()
    snapshot_target(spec, source)
    stages.seal_snapshot(source)
    baseline = dict(witnesses={'1': dict(x=2, outcome=1)}, exploration=dict(diagnostics='FP'))
    report = dict(stage=stage, status='baseline_missing', baseline=baseline, missing=[2])
    (source / 'result.json').write_text(json.dumps(report))
    return source


def test_target_build_is_driven_by_manifest_not_fdlibm_defaults(tmp_path):
    spec, _ = sample_target(tmp_path)
    directory = tmp_path / 'run'
    directory.mkdir()
    snapshot_target(spec, directory)
    target = variant_target(tmp_path, directory / 'original/driver.c', directory / 'library')
    assert target.sources == ['run/original/driver.c']
    assert target.cflags == []


def test_target_input_and_replay_contract_can_change(tmp_path):
    _, target = sample_target(tmp_path)
    target.update(replay_prefix='OTHER', outcomes=[7, 8])
    target['input'].update(name='number', min=10, max=20)
    objects = [dict(name='number', bytes=struct.pack('<d', 12))]
    assert decode_input(objects, target) == 12
    assert decode_replay('OTHER x=12 outcome=8\n', 12, target) == 8
    with pytest.raises(ValueError):
        decode_replay('OTHER x=12 outcome=1\n', 12, target)
    assert witnesses([dict(outcome=8)], target['outcomes']) == {'8': dict(outcome=8)}


def test_generation_uses_saved_target_without_container_and_retains_exchange(tmp_path):
    source = saved_stage(tmp_path)
    emitted, requests = [], []
    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=fixture_response()))],
                               usage=None, model='rehearsal-mock')
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    report = stages.execute_stage('generate', None, tmp_path, tmp_path / 'generated', source, None,
                                  dict(model='rehearsal-mock'), client, emitted.append)
    assert report['status'] == 'generated'
    assert 'FP' in requests[0]['messages'][0]['content']
    assert (tmp_path / 'generated/llm/response.md').is_file()
    assert (tmp_path / 'generated/surrogate.patch').is_file()
    assert (tmp_path / 'generated/original/guard.inc').read_text() == 'original guard'


def test_changed_original_snapshot_is_rejected(tmp_path):
    source = saved_stage(tmp_path)
    (source / 'original/guard.inc').write_text('modified')
    with pytest.raises(ValueError, match='snapshot changed'):
        stages.execute_stage('generate', None, tmp_path, tmp_path / 'new', source, None,
                             dict(model='mock'), None, lambda _: None)
    assert json.loads((tmp_path / 'new/result.json').read_text())['status'] == 'error'


def test_wrong_predecessor_or_failed_stage_cannot_be_consumed(tmp_path):
    source = saved_stage(tmp_path)
    with pytest.raises(ValueError, match='completed generate'):
        stages.read_stage(source, 'generate')
    report = json.loads((source / 'result.json').read_text())
    report['status'] = 'error'
    (source / 'result.json').write_text(json.dumps(report))
    with pytest.raises(ValueError, match='completed baseline'):
        stages.read_stage(source, 'baseline')


@pytest.mark.parametrize('observations,expected', [
    ([dict(x=2, outcome=1), dict(x=4, outcome=2)], 'SUCCESS'),
    ([dict(x=2, outcome=1), dict(error='failed replay')], 'INCOMPLETE'),
])
def test_success_requires_assisted_original_replays_for_every_outcome(tmp_path, monkeypatch, observations, expected):
    source = saved_stage(tmp_path)
    target = load_target(source / 'target.json')
    guard_hash = stages.write_surrogate(source, target, fixture_response(), lambda _: None)
    report = json.loads((source / 'result.json').read_text())
    report.update(stage='generate', status='generated', guard_sha256=guard_hash)
    (source / 'result.json').write_text(json.dumps(report))
    monkeypatch.setattr(stages, 'require_prepared_container', lambda _: None)
    monkeypatch.setattr(stages, 'observe', lambda *args: dict(
        observations=observations, witnesses=witnesses(observations, target['outcomes'])))
    emitted = []
    result = stages.execute_stage('assisted', None, tmp_path, tmp_path / 'after', source,
                                  None, {}, None, emitted.append)
    assert expected in emitted
    assert result['status'] == ('success' if expected == 'SUCCESS' else 'incomplete')


def test_reusing_a_stage_directory_is_rejected(tmp_path):
    directory = tmp_path / 'existing'
    directory.mkdir()
    with pytest.raises(FileExistsError):
        stages.execute_stage('baseline', None, tmp_path, directory, None, None, {}, None, print)


def test_stage_arguments_keep_provider_and_execution_independent():
    validate_stage_args(parser().parse_args(['baseline']))
    validate_stage_args(parser().parse_args(['assisted', '--from-run', 'runs/ghost']))
    with pytest.raises(ValueError, match='--model'):
        validate_stage_args(parser().parse_args(['generate', '--from-run', 'runs/base']))
    with pytest.raises(ValueError, match='snapshot'):
        validate_stage_args(parser().parse_args(['assisted', '--from-run', 'runs/ghost', '--target', 'other.json']))


def test_checker_reports_failure_and_keeps_checking():
    emitted = []
    assert not check('Key', lambda: (_ for _ in ()).throw(ValueError('secret')), emitted.append)
    assert check('Output', lambda: None, emitted.append)
    assert emitted == ['Key: FAIL', 'Output: OK']


def test_mock_model_listing_supports_noncompletion_probe():
    statuses = []
    body = b''.join(completion_app('unused')(
        dict(REQUEST_METHOD='GET', PATH_INFO='/v1/models'),
        lambda status, headers: statuses.append(status)))
    assert statuses == ['200 OK']
    assert json.loads(body)['data'][0]['id'] == 'rehearsal-mock'


def test_changed_generated_guard_is_rejected_before_execution(tmp_path):
    source = saved_stage(tmp_path)
    target = load_target(source / 'target.json')
    guard_hash = stages.write_surrogate(source, target, fixture_response(), lambda _: None)
    (source / 'result.json').write_text(json.dumps(dict(
        stage='generate', status='generated', guard_sha256=guard_hash)))
    (source / 'surrogate/guard.inc').write_text('modified generated guard')
    with pytest.raises(ValueError, match='generated guard changed'):
        stages.execute_stage('assisted', None, tmp_path, tmp_path / 'after', source,
                             None, {}, None, lambda _: None)
    assert json.loads((tmp_path / 'after/result.json').read_text())['status'] == 'error'
