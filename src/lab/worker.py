"""Lab worker: polls lab_jobs and runs each job in a child process.

The child is the bmtm-v2 interpreter running ``-m src.lab.runner <job_id>``,
started with nice(LAB_JOB_NICE), RLIMIT_AS = LAB_JOB_MEM_MB and a wall-clock
timeout. One job at a time by default (LAB_MAX_CONCURRENT_JOBS).

The worker itself never imports the engine, pandas or src.trading.
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import db as labdb
from . import queue as q
from .settings import REPO_ROOT, LabSettings, get_lab_settings

log = logging.getLogger("lab.worker")


def _child_preexec(nice: int, mem_mb: int) -> Callable[[], None]:
    def fn() -> None:
        os.setsid()  # own process group so a kill takes grandchildren too
        try:
            os.nice(nice)
        except OSError:
            pass
        if mem_mb > 0:
            try:
                import resource
                lim = mem_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
            except (ValueError, OSError, ImportError):
                pass  # e.g. macOS does not enforce RLIMIT_AS
    return fn


@dataclass
class Running:
    job: dict
    proc: subprocess.Popen
    started: float
    log_path: Path
    killed_reason: Optional[str] = None


@dataclass
class Worker:
    settings: LabSettings = field(default_factory=get_lab_settings)
    worker_id: str = field(default_factory=lambda: f"{socket.gethostname()}:{os.getpid()}")
    command: Optional[list[str]] = None  # override for tests
    stop_event: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        self.running: dict[int, Running] = {}
        self._last_reap = 0.0
        self._last_hb = 0.0
        self.log_dir = Path(self.settings.artifacts_dir) / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    # ── child management ───────────────────────────────────────────────
    def _cmd(self, job_id: int) -> list[str]:
        if self.command:
            return [*self.command, str(job_id)]
        return [self.settings.engine_python, "-m", "src.lab.runner", str(job_id)]

    def _spawn(self, job: dict) -> Running:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
        env["LAB_DB_PATH"] = self.settings.db_path
        env["LAB_ENGINE_PATH"] = self.settings.engine_path
        env["LAB_DATA_DIR"] = self.settings.data_dir
        env["LAB_ARTIFACTS_DIR"] = self.settings.artifacts_dir
        env["PYTHONUNBUFFERED"] = "1"
        log_path = self.log_dir / f"job-{job['id']}.log"
        fh = open(log_path, "ab")
        proc = subprocess.Popen(
            self._cmd(job["id"]), cwd=str(REPO_ROOT), env=env, stdout=fh, stderr=subprocess.STDOUT,
            preexec_fn=_child_preexec(self.settings.job_nice, self.settings.job_mem_mb),
        )
        fh.close()
        log.info("job %s (%s ref=%s) started pid=%s", job["id"], job["kind"], job["ref_id"], proc.pid)
        return Running(job=job, proc=proc, started=time.time(), log_path=log_path)

    def _kill(self, r: Running, reason: str) -> None:
        r.killed_reason = reason
        try:
            os.killpg(r.proc.pid, signal.SIGTERM)
            try:
                r.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(r.proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _tail(self, path: Path, n: int = 1500) -> str:
        try:
            data = path.read_bytes()[-n:]
            return data.decode("utf-8", "replace").strip()
        except OSError:
            return ""

    def _reap_children(self, conn) -> None:
        for job_id, r in list(self.running.items()):
            rc = r.proc.poll()
            if rc is None:
                continue
            del self.running[job_id]
            row = q.get_job(conn, job_id)
            if r.killed_reason == "cancelled":
                q.finish(conn, job_id, "cancelled", "cancelled by user")
            elif r.killed_reason:
                q.finish(conn, job_id, "error", r.killed_reason)
            elif row and row["status"] == "running":
                # child died without recording a result (crash, OOM, signal)
                q.finish(conn, job_id, "error",
                         f"engine process exited with code {rc}: {self._tail(r.log_path)[-800:]}")
            log.info("job %s finished rc=%s status=%s", job_id, rc,
                     (q.get_job(conn, job_id) or {}).get("status"))

    def _supervise(self, conn) -> None:
        now = time.time()
        do_hb = now - self._last_hb >= self.settings.heartbeat_s
        for job_id, r in list(self.running.items()):
            if r.proc.poll() is not None:
                continue
            if now - r.started > self.settings.job_timeout_s:
                self._kill(r, f"timeout after {self.settings.job_timeout_s}s")
                continue
            if do_hb:
                alive = q.heartbeat(conn, job_id, self.worker_id, pid=r.proc.pid)
                if not alive:
                    self._kill(r, "cancelled")
        if do_hb:
            self._last_hb = now

    # ── main loop ──────────────────────────────────────────────────────
    def tick(self, conn, hooks: Optional[list[Callable]] = None) -> None:
        self._reap_children(conn)
        self._supervise(conn)
        if time.time() - self._last_reap > 30:
            reaped = q.reap(conn, self.settings.stale_after_s)
            if reaped:
                log.warning("reaped stale jobs %s", reaped)
            self._last_reap = time.time()
        for hook in hooks or []:
            try:
                hook(conn)
            except Exception:  # noqa: BLE001
                log.exception("scheduler hook failed")
        while len(self.running) < max(1, self.settings.max_concurrent_jobs):
            job = q.claim(conn, self.worker_id)
            if job is None:
                break
            try:
                self.running[job["id"]] = self._spawn(job)
            except Exception as e:  # noqa: BLE001
                q.finish(conn, job["id"], "error", f"spawn failed: {e}")

    def run_forever(self, hooks: Optional[list[Callable]] = None) -> None:
        conn = labdb.connect(self.settings.db_path)
        log.info("lab worker %s started (db=%s, engine=%s)", self.worker_id, self.settings.db_path,
                 self.settings.engine_path)
        try:
            while not self.stop_event.is_set():
                self.tick(conn, hooks)
                self.stop_event.wait(self.settings.poll_s)
        finally:
            for r in list(self.running.values()):
                self._kill(r, "worker shutdown")
            self._reap_children(conn)
            conn.close()

    def run_until_idle(self, timeout_s: float = 600, hooks: Optional[list[Callable]] = None) -> None:
        """Test/CLI helper: process queued jobs until none are queued or running."""
        conn = labdb.connect(self.settings.db_path)
        t0 = time.time()
        try:
            while time.time() - t0 < timeout_s:
                self.tick(conn, hooks)
                queued = conn.execute("SELECT COUNT(*) FROM lab_jobs WHERE status IN ('queued','running')"
                                      ).fetchone()[0]
                if not queued and not self.running:
                    return
                time.sleep(0.5)
            raise TimeoutError("jobs still pending")
        finally:
            conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    w = Worker()

    def _stop(*_):
        w.stop_event.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    hooks: list[Callable] = []
    try:
        from .scheduler import Scheduler
        hooks.append(Scheduler(w.settings).tick)
    except ImportError:
        pass
    w.run_forever(hooks)


if __name__ == "__main__":
    main()
