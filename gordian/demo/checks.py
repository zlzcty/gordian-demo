"""Readiness checks with simple labels and no implicit container lifecycle changes."""
from __future__ import annotations

import importlib
import shutil
import sys
import tempfile
from pathlib import Path

from ..klee import compile_bitcode
from .execution import build_original_replay, variant_target
from .model import api_key, endpoint_config, make_client
from .target import load_target, snapshot_target, target_files


def require(condition: bool) -> None:
    if not condition:
        raise ValueError("check failed")


def check(label, action, emit) -> bool:
    try:
        action()
    except Exception:
        emit(f"{label}: FAIL")
        return False
    emit(f"{label}: OK")
    return True


def check_packages() -> None:
    for package in ("gordian", "openai", "yaml"):
        importlib.import_module(package)


def check_target(path: Path) -> None:
    target = load_target(path)
    for file in target_files(target, path.parent):
        require(file.is_file())
        file.read_bytes()


def check_output(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory):
        pass


def check_tools(container) -> None:
    tools = container.probe(force=True)
    for tool in (tools.klee, tools.clang, tools.llvm_link, tools.llvm_profdata, tools.llvm_cov):
        require(bool(tool))
        require(container.exec([tool, "--help"], timeout=10).returncode == 0)


def check_build(container, root, runs, target_path) -> None:
    with tempfile.TemporaryDirectory(prefix=".demo-check-", dir=runs) as temporary:
        directory = Path(temporary)
        snapshot_target(target_path, directory)
        driver, library = directory / "original/driver.c", directory / "library"
        build_original_replay(container, driver, directory / "native", library)
        target = variant_target(root, driver, library)
        require(compile_bitcode(container, target, root, directory / "build").ok)


def check_model_settings(args, environment) -> None:
    endpoint_config(args.provider, args.base_url, args.key_env)
    require(bool(args.model))


def check_key(args, environment) -> None:
    _, name = endpoint_config(args.provider, args.base_url, args.key_env)
    api_key(environment, name)


def probe_model(args, environment) -> None:
    url, name = endpoint_config(args.provider, args.base_url, args.key_env)
    client = make_client(url, api_key(environment, name), args.request_seconds)
    try:
        require(any(model.id == args.model for model in client.models.list()))
    finally:
        client.close()


def run_checks(args, settings, container, environment, emit) -> int:
    root = settings.project_root.resolve()
    target_path = (args.target or root / "demos/trig/target.json").resolve()
    checks = readiness_checks(args, settings, container, environment, target_path)
    results = [check(label, action, emit) for label, action in checks]
    return 0 if all(results) else 1


def readiness_checks(args, settings, container, environment, target_path) -> list:
    checks = [
        ("Settings", lambda: require(settings.project_root.is_dir())),
        ("Python", lambda: require(sys.version_info >= (3, 10))),
        ("Packages", check_packages),
        ("Docker", lambda: require(shutil.which(settings.docker_bin) is not None)),
        ("Container", lambda: require(container.running())),
        ("Mount", lambda: require(container.mount_ok())),
        ("Tools", lambda: check_tools(container)),
        ("Target", lambda: check_target(target_path)),
        ("Output", lambda: check_output(settings.runs)),
        ("Build", lambda: check_build(container, settings.project_root.resolve(), settings.runs, target_path)),
    ]
    if args.check_model or args.probe_model:
        checks.extend([
            ("Model", lambda: check_model_settings(args, environment)),
            ("Key", lambda: check_key(args, environment)),
        ])
    if args.probe_model:
        checks.append(("Endpoint", lambda: probe_model(args, environment)))
    return checks
