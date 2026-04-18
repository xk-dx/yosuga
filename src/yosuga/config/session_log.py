import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class SessionLogger:
    def __init__(self, workspace_root: Path, relative_dir: str, session_id: str | None = None):
        self.session_id = session_id or uuid.uuid4().hex
        self._dir = (workspace_root / relative_dir).resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / f"{self.session_id}.jsonl"

    @property
    def path(self) -> Path:
        return self._path

    def log(self, event_type: str, payload: Dict[str, Any]) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "event_type": event_type,
            "payload": payload,
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
