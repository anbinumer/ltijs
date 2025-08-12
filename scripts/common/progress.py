import json
import sys
from typing import Optional, Dict, Any


class ProgressReporter:
    """Small helper to emit newline-delimited JSON progress events to stdout.

    The Node.js backend listens for lines prefixed with:
    - PROGRESS: { ... }
    - DONE: { ... }
    - ERROR: { ... }
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def _emit(self, prefix: str, payload: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            sys.stdout.write(f"{prefix} {json.dumps(payload)}\n")
            sys.stdout.flush()
        except Exception:
            # Never fail the script due to progress reporting
            pass

    def update(self, step: str, current: Optional[int] = None, total: Optional[int] = None, message: Optional[str] = None) -> None:
        payload: Dict[str, Any] = {"step": step}
        if current is not None:
            payload["current"] = int(current)
        if total is not None:
            payload["total"] = int(total)
        if message is not None:
            payload["message"] = message
        self._emit("PROGRESS:", payload)

    def done(self, payload: Optional[Dict[str, Any]] = None) -> None:
        self._emit("DONE:", payload or {"ok": True})

    def error(self, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        payload: Dict[str, Any] = {"message": message}
        if extra:
            payload.update(extra)
        self._emit("ERROR:", payload)


