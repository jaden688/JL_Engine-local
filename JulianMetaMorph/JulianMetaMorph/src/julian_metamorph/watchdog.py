"""
SparkByte watchdog — runs inside MetaMorph.

Polls SparkByte's /health endpoint every POLL_INTERVAL_S seconds.
After FAIL_THRESHOLD consecutive failures it fires a restart by launching
`julia --project=. sparkbyte.jl` in SPARKBYTE_DIR.

Control:
    watchdog.pause()   — stop polling (e.g. during intentional restart)
    watchdog.resume()  — re-enable polling
    watchdog.status()  — dict of current state
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import urllib.request
import urllib.error

logger = logging.getLogger("sparkbyte.watchdog")

# ------------------------------------------------------------------
# Configuration (override via env-vars)
# ------------------------------------------------------------------
SPARKBYTE_HEALTH_URL: str = os.environ.get(
    "SPARKBYTE_HEALTH_URL", "http://127.0.0.1:8081/health"
)
POLL_INTERVAL_S: float = float(os.environ.get("WATCHDOG_POLL_S", "15"))
FAIL_THRESHOLD: int = int(os.environ.get("WATCHDOG_FAIL_THRESHOLD", "3"))
RESTART_COOLDOWN_S: float = float(os.environ.get("WATCHDOG_COOLDOWN_S", "60"))

# Directory where `julia --project=. sparkbyte.jl` should be run.
_DEFAULT_SB_DIR = Path(__file__).resolve().parents[4]  # …/JL_Engine-SB.Omni
SPARKBYTE_DIR: Path = Path(
    os.environ.get("SPARKBYTE_DIR", str(_DEFAULT_SB_DIR))
)


class SparkByteWatchdog:
    def __init__(self) -> None:
        self._paused = False
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        self.consecutive_failures: int = 0
        self.total_failures: int = 0
        self.total_restarts: int = 0
        self.last_ok: datetime | None = None
        self.last_failure: datetime | None = None
        self.last_restart: datetime | None = None
        self.last_restart_reason: str = ""
        self._restart_proc: subprocess.Popen | None = None  # type: ignore[type-arg]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="sparkbyte-watchdog", daemon=True
        )
        self._thread.start()
        logger.info(
            "SparkByte watchdog started (url=%s poll=%ss threshold=%d)",
            SPARKBYTE_HEALTH_URL,
            POLL_INTERVAL_S,
            FAIL_THRESHOLD,
        )

    def stop(self) -> None:
        with self._lock:
            self._running = False

    def pause(self) -> None:
        self._paused = True
        logger.info("SparkByte watchdog paused")

    def resume(self) -> None:
        self._paused = False
        self.consecutive_failures = 0
        logger.info("SparkByte watchdog resumed")

    def status(self) -> dict[str, object]:
        return {
            "paused": self._paused,
            "running": self._running,
            "consecutive_failures": self.consecutive_failures,
            "fail_threshold": FAIL_THRESHOLD,
            "total_failures": self.total_failures,
            "total_restarts": self.total_restarts,
            "last_ok": self.last_ok.isoformat() if self.last_ok else None,
            "last_failure": self.last_failure.isoformat() if self.last_failure else None,
            "last_restart": self.last_restart.isoformat() if self.last_restart else None,
            "last_restart_reason": self.last_restart_reason,
            "health_url": SPARKBYTE_HEALTH_URL,
            "sparkbyte_dir": str(SPARKBYTE_DIR),
            "poll_interval_s": POLL_INTERVAL_S,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _loop(self) -> None:
        while True:
            with self._lock:
                if not self._running:
                    break
            time.sleep(POLL_INTERVAL_S)
            if self._paused:
                continue
            self._tick()

    def _tick(self) -> None:
        ok = self._check_health()
        now = datetime.now(tz=timezone.utc)
        if ok:
            self.last_ok = now
            self.consecutive_failures = 0
        else:
            self.last_failure = now
            self.consecutive_failures += 1
            self.total_failures += 1
            logger.warning(
                "SparkByte health check failed (%d/%d)",
                self.consecutive_failures,
                FAIL_THRESHOLD,
            )
            if self.consecutive_failures >= FAIL_THRESHOLD:
                self._restart("health check failed x%d" % self.consecutive_failures)

    def _check_health(self) -> bool:
        try:
            req = urllib.request.Request(SPARKBYTE_HEALTH_URL, method="GET")
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _restart(self, reason: str) -> None:
        now = datetime.now(tz=timezone.utc)

        # Enforce cooldown to avoid a rapid restart storm.
        if self.last_restart is not None:
            elapsed = (now - self.last_restart).total_seconds()
            if elapsed < RESTART_COOLDOWN_S:
                logger.info(
                    "Restart requested (%s) but still in cooldown (%.0fs left)",
                    reason,
                    RESTART_COOLDOWN_S - elapsed,
                )
                return

        # If previous Julia process is still running, let it die naturally.
        if self._restart_proc is not None and self._restart_proc.poll() is None:
            logger.info("Previous restart process still alive — skipping new launch")
            return

        logger.warning("🔁 Restarting SparkByte — reason: %s", reason)
        self.last_restart = now
        self.last_restart_reason = reason
        self.total_restarts += 1
        self.consecutive_failures = 0
        self._paused = True  # pause until julia is up

        log_out = open(
            SPARKBYTE_DIR / "logs" / "watchdog_restart.log", "a", encoding="utf-8"
        )
        log_out.write(f"\n[{now.isoformat()}] WATCHDOG RESTART — {reason}\n")
        log_out.flush()

        try:
            self._restart_proc = subprocess.Popen(
                ["julia", "--project=.", "sparkbyte.jl"],
                cwd=str(SPARKBYTE_DIR),
                stdout=log_out,
                stderr=log_out,
                env={**os.environ, "SPARKBYTE_LAUNCH_BROWSER": "0"},
                # Detach from MetaMorph so MetaMorph exit ≠ SparkByte death.
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP")
                else 0,
            )
            logger.info(
                "SparkByte restarted — PID %d", self._restart_proc.pid
            )
        except Exception as exc:
            logger.error("Failed to restart SparkByte: %s", exc)
            self._paused = False
            return

        # Re-enable polling after the process has had time to boot.
        def _unpause_after_boot() -> None:
            time.sleep(RESTART_COOLDOWN_S)
            self._paused = False
            logger.info("Watchdog polling resumed after restart cooldown")

        threading.Thread(target=_unpause_after_boot, daemon=True).start()


# Module-level singleton used by service.py
_watchdog = SparkByteWatchdog()


def get_watchdog() -> SparkByteWatchdog:
    return _watchdog
