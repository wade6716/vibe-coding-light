"""Session manager for the ESP8266 signal light.

Manages multiple coding-agent sessions, maps their signals to LED patterns,
and computes an aggregate pattern for the hardware.  All state is persisted
to a JSON file protected by a file lock, so multiple processes can
contribute signals concurrently.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

logger = logging.getLogger("signal_light.session_manager")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SESSION_TTL_SECONDS = 86400       # 24 hours
ENDED_TTL_SECONDS = 600           # 10 minutes
STATE_FILE = Path(tempfile.gettempdir()) / "signal-light-sessions.json"

# Maps incoming signal names to the LED pattern understood by the ESP8266.
SIGNAL_TO_PATTERN: Dict[str, str] = {
    "idle":         "green_on",
    "session_start": "green_on",
    "session_end":   "green_on",
    "thinking":      "work_cycle",
    "working":       "work_cycle",
    "tool_done":     "work_cycle",
    "attention":     "flash_yellow",
    "permission":    "flash_yellow",
    "done":          "flash_yellow",
    "blocked":       "flash_red",
    "session_done":  "notice_green",
    "turn_end":      "notice_green",
    "off":           "off",
}

# Highest-priority signal wins when multiple sessions are live.
PRIORITY_ORDER = ["blocked", "permission", "attention", "working", "idle"]

_SIGNAL_TO_CATEGORY: Dict[str, str] = {
    "blocked":    "blocked",
    "permission": "permission",
    "attention":  "attention",
    "done":       "attention",
    "thinking":   "working",
    "working":    "working",
    "tool_done":  "working",
    "idle":       "idle",
    "session_start": "idle",
    "session_end":   "idle",
    "off":           "idle",
}

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SignalResult:
    """Result returned by :meth:`SessionManager.handle_signal`."""

    pattern: str        # The pattern to send to the ESP8266
    notice_first: bool  # If True, send notice_green to ESP first


# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------

class SessionManager:
    """File-backed, concurrency-safe session manager for the signal light."""

    def __init__(self, state_file: Path = STATE_FILE) -> None:
        self._state_file = state_file
        self._lock_file = state_file.with_suffix(".lock")

    # -- public API ---------------------------------------------------------

    def handle_signal(self, session_id: str, signal: str) -> SignalResult:
        """Process *signal* for *session_id* and return the LED pattern.

        The method acquires an exclusive file lock for the entire duration so
        that concurrent callers are serialised correctly.
        """
        notice_first = False

        with open(self._lock_file, "w") as lock_fp:
            fcntl.flock(lock_fp, fcntl.LOCK_EX)
            try:
                state = self._load_state()
                now = time.time()
                state = self._prune_expired(state, now)

                sessions: dict = state["sessions"]
                ended: dict = state["ended"]
                existed = session_id in sessions

                # -- apply signal -------------------------------------------
                logger.info(
                    "Processing signal=%r session=%s existed=%s ended=%s",
                    signal, session_id, existed, list(ended.keys()),
                )

                if signal in ("session_end", "session_done"):
                    if existed:
                        del sessions[session_id]
                        self._mark_session_ended(state, session_id, now)
                        notice_first = True

                elif signal == "off":
                    sessions.pop(session_id, None)
                    # No ended marker for explicit off.

                elif signal == "turn_end":
                    if existed:
                        if self._is_urgent_signal(sessions[session_id]["signal"]):
                            pass  # keep session, no notice
                        else:
                            del sessions[session_id]
                            self._mark_session_ended(state, session_id, now)
                            notice_first = True
                    else:
                        self._mark_session_ended(state, session_id, now)

                elif signal == "session_start":
                    self._clear_session_ended(state, session_id)
                    sessions[session_id] = {"signal": signal, "updated_at": now}

                elif signal == "thinking":
                    # UserPromptSubmit = new task begins — clear ended marker
                    # so the same session ID can be reused.
                    self._clear_session_ended(state, session_id)
                    sessions[session_id] = {"signal": signal, "updated_at": now}

                else:
                    # Other signals: ignore if session is ended, else upsert.
                    if self._is_session_ended(state, session_id, now):
                        logger.info(
                            "Ignoring signal %r for ended session %s",
                            signal, session_id,
                        )
                    else:
                        sessions[session_id] = {"signal": signal, "updated_at": now}

                # -- compute aggregate --------------------------------------
                # Prune stale idle-category sessions (thinking/idle/session_start
                # that haven't been updated in 60s — likely from a crashed process).
                IDLE_STALE_SECONDS = 60
                idle_signals = {"idle", "thinking", "session_start", "session_end"}
                stale = [
                    sid for sid, info in sessions.items()
                    if info.get("signal") in idle_signals
                    and (now - info.get("updated_at", 0)) > IDLE_STALE_SECONDS
                ]
                for sid in stale:
                    logger.info("Pruning stale idle session %s", sid)
                    del sessions[sid]

                aggregate = self._compute_aggregate(sessions)
                pattern = SIGNAL_TO_PATTERN.get(aggregate, "green_on")
                logger.info(
                    "Result: aggregate=%s pattern=%s notice_first=%s sessions=%s",
                    aggregate, pattern, notice_first, list(sessions.keys()),
                )

                self._save_state(state)
            finally:
                fcntl.flock(lock_fp, fcntl.LOCK_UN)

        return SignalResult(pattern=pattern, notice_first=notice_first)

    def get_status(self) -> dict:
        """Return current sessions, ended markers, and the aggregate signal."""
        with open(self._lock_file, "w") as lock_fp:
            fcntl.flock(lock_fp, fcntl.LOCK_EX)
            try:
                state = self._load_state()
                now = time.time()
                state = self._prune_expired(state, now)
                aggregate = self._compute_aggregate(state["sessions"])
                return {
                    "sessions": state["sessions"],
                    "ended": state["ended"],
                    "aggregate": aggregate,
                }
            finally:
                fcntl.flock(lock_fp, fcntl.LOCK_UN)

    def reset(self) -> int:
        """Clear all state.  Returns the number of sessions that were live."""
        with open(self._lock_file, "w") as lock_fp:
            fcntl.flock(lock_fp, fcntl.LOCK_EX)
            try:
                state = self._load_state()
                count = len(state["sessions"])
                self._save_state({"sessions": {}, "ended": {}})
                return count
            finally:
                fcntl.flock(lock_fp, fcntl.LOCK_UN)

    # -- private helpers ----------------------------------------------------

    def _load_state(self) -> dict:
        """Load state from disk, returning an empty structure on failure."""
        try:
            with open(self._state_file, "r") as fp:
                data = json.load(fp)
                # Ensure both keys exist.
                data.setdefault("sessions", {})
                data.setdefault("ended", {})
                return data
        except FileNotFoundError:
            return {"sessions": {}, "ended": {}}
        except json.JSONDecodeError:
            logger.warning(
                "Corrupt state file %s; starting with empty state.",
                self._state_file,
            )
            return {"sessions": {}, "ended": {}}

    def _save_state(self, state: dict) -> None:
        """Atomically write *state* to the state file."""
        tmp_file = self._state_file.with_suffix(".tmp")
        with open(tmp_file, "w") as fp:
            json.dump(state, fp, indent=2, sort_keys=True)
        os.rename(tmp_file, self._state_file)

    @staticmethod
    def _prune_expired(state: dict, now: float) -> dict:
        """Remove sessions older than SESSION_TTL and ended markers older than ENDED_TTL."""
        sessions = state["sessions"]
        ended = state["ended"]

        stale_sessions = [
            sid for sid, info in sessions.items()
            if (now - info.get("updated_at", 0)) > SESSION_TTL_SECONDS
        ]
        for sid in stale_sessions:
            logger.info("Pruning expired session %s", sid)
            del sessions[sid]

        stale_ended = [
            sid for sid, info in ended.items()
            if (now - info.get("removed_at", 0)) > ENDED_TTL_SECONDS
        ]
        for sid in stale_ended:
            del ended[sid]

        return state

    @staticmethod
    def _is_session_ended(state: dict, session_id: str, now: float) -> bool:
        """Return True if *session_id* is in the ended set and not yet expired."""
        info = state["ended"].get(session_id)
        if info is None:
            return False
        return (now - info.get("removed_at", 0)) <= ENDED_TTL_SECONDS

    @staticmethod
    def _mark_session_ended(state: dict, session_id: str, now: float) -> None:
        """Record that *session_id* was ended at *now*."""
        state["ended"][session_id] = {"removed_at": now}

    @staticmethod
    def _clear_session_ended(state: dict, session_id: str) -> None:
        """Remove *session_id* from the ended set (e.g. on session restart)."""
        state["ended"].pop(session_id, None)

    @staticmethod
    def _is_urgent_signal(signal: str) -> bool:
        """Return True if *signal* is permission or blocked."""
        return signal in ("permission", "blocked")

    @staticmethod
    def _compute_aggregate(sessions: dict) -> str:
        """Return the highest-priority signal across all live sessions."""
        categories = set()
        for info in sessions.values():
            cat = _SIGNAL_TO_CATEGORY.get(info.get("signal", ""), "idle")
            categories.add(cat)

        for signal in PRIORITY_ORDER:
            if signal in categories:
                return signal
        return "idle"
