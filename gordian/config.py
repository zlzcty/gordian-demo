"""Project settings.

Everything Gordian needs to know about the host and the Docker backends lives
in one YAML file, ``gordian.yaml`` at the project root (created by
``gordian init``).  Paths are relative to the project root unless absolute.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_MOUNT = "/gordian"


@dataclass
class ContainerSpec:
    name: str
    image: str
    user: Optional[str] = None  # None = image default


@dataclass
class Settings:
    project_root: Path
    mount_path: str = DEFAULT_MOUNT
    std: ContainerSpec = field(default_factory=lambda: ContainerSpec("gordian-klee", "klee/klee:3.0"))
    float: ContainerSpec = field(default_factory=lambda: ContainerSpec("gordian-klee-float", "gordian-klee-float:latest"))
    runs_dir: str = "runs"
    benchmarks_dir: str = "benchmarks"
    cache_dir: str = "llm_cache"
    # KLEE defaults (KLEE's standard configuration)
    solver_timeout_s: int = 20
    explore_solver_timeout_s: int = 2          # "solver timeout reduced by 90%" for the exploratory run
    search: str = "bfs"
    replay_timeout_s: int = 30
    replay_max_tests: int = 0                  # 0 = replay every test; >0 = evenly spaced sample of at most that many
    docker_bin: str = "docker"

    @property
    def runs(self) -> Path:
        return self.project_root / self.runs_dir

    @property
    def benchmarks(self) -> Path:
        return self.project_root / self.benchmarks_dir

    @property
    def cache(self) -> Path:
        return self.project_root / self.cache_dir

    def to_container(self, host_path: Path | str) -> str:
        p = Path(host_path).resolve()
        try:
            rel = p.relative_to(self.project_root.resolve())
        except ValueError as exc:
            raise ValueError(f"{p} is outside the project root {self.project_root}; only the project root is mounted") from exc
        return f"{self.mount_path}/{rel.as_posix()}".rstrip("/")

    def to_host(self, container_path: str) -> Path:
        assert container_path.startswith(self.mount_path), container_path
        return self.project_root / container_path[len(self.mount_path):].lstrip("/")

    def dump(self) -> dict:
        d = asdict(self)
        d["project_root"] = str(self.project_root)
        return d

    def save(self, path: Optional[Path] = None) -> Path:
        path = path or self.project_root / "gordian.yaml"
        path.write_text(yaml.safe_dump(self.dump(), sort_keys=False))
        return path


def find_project_root(start: Optional[Path] = None) -> Path:
    env = os.environ.get("GORDIAN_ROOT")
    if env:
        return Path(env).resolve()
    p = (start or Path.cwd()).resolve()
    for cand in [p, *p.parents]:
        if (cand / "gordian.yaml").exists():
            return cand
    return Path(__file__).resolve().parents[1]


def load_settings(root: Optional[Path] = None) -> Settings:
    root = Path(root).resolve() if root else find_project_root()
    cfg = root / "gordian.yaml"
    data = yaml.safe_load(cfg.read_text()) if cfg.exists() else {}
    data = data or {}
    s = Settings(project_root=root)
    for k, v in data.items():
        if k in ("std", "float"):
            setattr(s, k, ContainerSpec(**v))
        elif k == "project_root":
            continue
        elif hasattr(s, k):
            setattr(s, k, v)
    # env overrides for the two images / names
    s.std.image = os.environ.get("GORDIAN_KLEE_IMAGE", s.std.image)
    s.float.image = os.environ.get("GORDIAN_KLEE_FLOAT_IMAGE", s.float.image)
    return s
