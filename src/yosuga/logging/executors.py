from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class SessionStore:
    def __init__(self, workspace_root: Path, relative_dir: str, session_id: str | None = None):
        self.session_id = session_id or uuid.uuid4().hex
        self.root_dir = (workspace_root / relative_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir = self.root_dir / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.session_dir / "session.jsonl"


class JsonlLogExecutor:
    def __init__(self, store: SessionStore):
        self.store = store

    def append(self, event_type: str, payload: Dict[str, Any]) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.store.session_id,
            "event_type": event_type,
            "payload": payload,
        }
        with self.store.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
