"""Docker-backed KLEE containers.

One long-lived container per backend (standard KLEE, KLEE-Float).  The whole
project root is bind-mounted at ``settings.mount_path`` so that every path on
the host maps to a path in the container by prefix substitution and no
``docker cp`` is ever needed.  Tool locations (klee, libkleeRuntest, clang,
llvm-cov ...) are probed once per container and cached in
``runs/.docker/<container>.json``.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from .config import Settings, ContainerSpec
from .log import get_logger

log = get_logger(__name__)


@dataclass
class ToolPaths:
    klee: str
    klee_include: str          # directory containing klee/klee.h
    klee_runtest_lib: str      # directory containing libkleeRuntest.so
    clang: str
    llvm_link: str
    llvm_profdata: str
    llvm_cov: str
    ktest_tool: str
    klee_version: str
    is_float: bool


class ExecResult(subprocess.CompletedProcess):
    pass


class Container:
    def __init__(self, settings: Settings, spec: ContainerSpec, is_float: bool):
        self.settings = settings
        self.spec = spec
        self.is_float = is_float
        self.docker = settings.docker_bin
        self._tools: Optional[ToolPaths] = None

    # ---- lifecycle ----------------------------------------------------------
    def _inspect(self, fmt: str) -> Optional[str]:
        r = subprocess.run([self.docker, "inspect", "-f", fmt, self.spec.name], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None

    def exists(self) -> bool:
        return self._inspect("{{.Id}}") is not None

    def running(self) -> bool:
        return self._inspect("{{.State.Running}}") == "true"

    def mount_ok(self) -> bool:
        mounts = self._inspect("{{json .Mounts}}")
        if not mounts:
            return False
        want_src = str(self.settings.project_root.resolve())
        for m in json.loads(mounts):
            if m.get("Destination") == self.settings.mount_path and m.get("Source") == want_src:
                return True
        return False

    def up(self, recreate: bool = False) -> None:
        if self.exists() and (recreate or not self.mount_ok()):
            if not recreate:
                log.warning("container %s exists with a different mount; recreating it", self.spec.name)
            subprocess.run([self.docker, "rm", "-f", self.spec.name], capture_output=True)
        if not self.exists():
            cmd = [self.docker, "run", "-d", "--name", self.spec.name,
                   "-v", f"{self.settings.project_root.resolve()}:{self.settings.mount_path}",
                   "-w", self.settings.mount_path]
            if self.spec.user:
                cmd += ["--user", self.spec.user]
            cmd += [self.spec.image, "sleep", "infinity"]
            log.info("creating container %s from %s", self.spec.name, self.spec.image)
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        elif not self.running():
            log.info("starting container %s", self.spec.name)
            subprocess.run([self.docker, "start", self.spec.name], check=True, capture_output=True)
        self.probe(force=True)

    def down(self) -> None:
        if self.exists():
            subprocess.run([self.docker, "rm", "-f", self.spec.name], capture_output=True)

    def ensure_running(self) -> None:
        if not (self.exists() and self.running() and self.mount_ok()):
            self.up()

    # ---- execution ----------------------------------------------------------
    def exec(self, cmd: str | list[str], *, cwd: Optional[str] = None, timeout: Optional[float] = None,
             env: Optional[dict] = None, check: bool = False, input: Optional[str] = None) -> subprocess.CompletedProcess:
        """Run a shell command (string) or argv (list) inside the container."""
        if isinstance(cmd, list):
            cmd = " ".join(shlex.quote(c) for c in cmd)
        full = [self.docker, "exec", "-i"]
        if cwd:
            full += ["-w", cwd]
        for k, v in (env or {}).items():
            full += ["-e", f"{k}={v}"]
        full += [self.spec.name, "bash", "-lc", cmd]
        t0 = time.time()
        try:
            r = subprocess.run(full, capture_output=True, text=True, timeout=timeout, input=input)
        except subprocess.TimeoutExpired as exc:
            log.warning("docker exec timed out after %.0fs: %s", time.time() - t0, cmd[:200])
            r = subprocess.CompletedProcess(full, returncode=124, stdout=(exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
                                            stderr=(exc.stderr or b"").decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or ""))
        if check and r.returncode != 0:
            raise RuntimeError(f"command failed ({r.returncode}) in {self.spec.name}: {cmd}\n{r.stderr[-4000:]}")
        return r

    def path(self, host_path: Path | str) -> str:
        return self.settings.to_container(host_path)

    # ---- tool discovery -------------------------------------------------------
    def _probe_file(self) -> Path:
        d = self.settings.runs / ".docker"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{self.spec.name}.json"

    def probe(self, force: bool = False) -> ToolPaths:
        if self._tools and not force:
            return self._tools
        f = self._probe_file()
        if f.exists() and not force:
            self._tools = ToolPaths(**json.loads(f.read_text()))
            return self._tools
        script = r'''
set -e
K=$(command -v klee || ls /usr/local/bin/klee /home/klee/klee_build/bin/klee /tmp/klee_build*/bin/klee 2>/dev/null | head -1)
[ -n "$K" ] || { echo "NO_KLEE"; exit 1; }
BIN=$(dirname "$K")
# candidate roots: the klee build tree, /usr/local, the klee source tree
RT=""
for d in "$BIN/../lib" /usr/local/lib64 /usr/local/lib /home/klee/klee_build/lib /tmp/klee_build*/lib; do
  if ls "$d"/libkleeRuntest.so* >/dev/null 2>&1; then RT=$(cd "$d" && pwd); break; fi
done
INC=""
for d in /usr/include /usr/local/include "$BIN/../include" /home/klee/klee_src/include /tmp/klee_src/include /home/user/klee/include; do
  if [ -f "$d/klee/klee.h" ]; then INC=$(cd "$d" && pwd); break; fi
done
echo "KLEE=$K"
echo "RT=$RT"
echo "INC=$INC"
echo "CLANG=$(command -v clang)"
echo "LLVM_LINK=$(command -v llvm-link)"
echo "LLVM_PROFDATA=$(command -v llvm-profdata)"
echo "LLVM_COV=$(command -v llvm-cov)"
echo "KTEST_TOOL=$(command -v ktest-tool || true)"
echo "VERSION=$($K --version 2>&1 | head -1)"
'''
        r = self.exec(script, timeout=60)
        if r.returncode != 0 or "NO_KLEE" in r.stdout:
            raise RuntimeError(f"could not find klee inside {self.spec.name}: {r.stdout} {r.stderr}")
        kv = dict(line.split("=", 1) for line in r.stdout.strip().splitlines() if "=" in line)
        tools = ToolPaths(klee=kv["KLEE"], klee_include=kv["INC"], klee_runtest_lib=kv["RT"], clang=kv["CLANG"],
                          llvm_link=kv["LLVM_LINK"], llvm_profdata=kv["LLVM_PROFDATA"], llvm_cov=kv["LLVM_COV"],
                          ktest_tool=kv.get("KTEST_TOOL", ""), klee_version=kv["VERSION"], is_float=self.is_float)
        # Replay (coverage) always runs in the standard container; the float backend only needs klee+clang.
        required = ("klee_include", "clang") if self.is_float else ("klee_include", "klee_runtest_lib", "clang", "llvm_profdata", "llvm_cov")
        missing = [k for k in required if not getattr(tools, k)]
        if missing:
            raise RuntimeError(f"container {self.spec.name} lacks required tools: {missing} ({kv})")
        f.write_text(json.dumps(asdict(tools), indent=2))
        self._tools = tools
        log.info("%s: %s", self.spec.name, tools.klee_version)
        return tools

    @property
    def tools(self) -> ToolPaths:
        return self.probe()


class Runtime:
    """Both containers, selected by ``float`` flag."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.std = Container(settings, settings.std, is_float=False)
        self.float = Container(settings, settings.float, is_float=True)

    def get(self, use_float: bool) -> Container:
        return self.float if use_float else self.std

    def up(self, recreate: bool = False, which: Optional[str] = None) -> None:
        for name, c in (("std", self.std), ("float", self.float)):
            if which in (None, name):
                try:
                    c.up(recreate=recreate)
                except Exception as exc:  # noqa: BLE001
                    log.error("could not start %s container (%s): %s", name, c.spec.image, exc)
                    if which == name:
                        raise

    def status(self) -> dict:
        out = {}
        for name, c in (("std", self.std), ("float", self.float)):
            out[name] = dict(name=c.spec.name, image=c.spec.image, exists=c.exists(), running=c.running(),
                             mount_ok=c.mount_ok())
            if out[name]["running"] and out[name]["mount_ok"]:
                try:
                    out[name]["klee"] = c.probe().klee_version
                except Exception as exc:  # noqa: BLE001
                    out[name]["klee"] = f"probe failed: {exc}"
        return out
