import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class SessionLogger:
    def __init__(self, workspace_root: Path, relative_dir: str, session_id: str | None = None):
        self.session_id = session_id or uuid.uuid4().hex
        self._root_dir = (workspace_root / relative_dir).resolve()
        self._root_dir.mkdir(parents=True, exist_ok=True)
        self._session_dir = self._root_dir / self.session_id
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._session_dir / "session.jsonl"

    @property
    def session_dir(self) -> Path:
        return self._session_dir

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


def find_latest_session_id(workspace_root: Path, relative_dir: str) -> Optional[str]:
    root = (workspace_root / relative_dir).resolve()
    if not root.exists() or not root.is_dir():
        return None

    candidates: List[Tuple[float, str]] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        ckpt_file = child / "history.ckpt.json"
        if not ckpt_file.exists() or not ckpt_file.is_file():
            continue
        try:
            candidates.append((ckpt_file.stat().st_mtime, child.name))
        except Exception:
            continue

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def load_history_ckpt(session_dir: Path) -> Tuple[List[Dict[str, Any]], int]:
    ckpt_file = session_dir / "history.ckpt.json"
    if not ckpt_file.exists() or not ckpt_file.is_file():
        return [], 0

    try:
        data = json.loads(ckpt_file.read_text(encoding="utf-8"))
    except Exception:
        return [], 0

    if not isinstance(data, dict):
        return [], 0

    history = data.get("history", [])
    turn_index_raw = data.get("turn_index", 0)
    if not isinstance(history, list):
        history = []
    try:
        turn_index = int(turn_index_raw)
    except Exception:
        turn_index = 0

    # Keep only role/content pairs to avoid malformed checkpoint payloads.
    safe_history: List[Dict[str, Any]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip()
        if role not in {"user", "assistant"}:
            continue
        if "content" not in item:
            continue
        safe_history.append({"role": role, "content": item.get("content")})

    return safe_history, max(0, turn_index)


def save_history_ckpt(session_dir: Path, history: List[Dict[str, Any]], turn_index: int) -> None:
    ckpt_file = session_dir / "history.ckpt.json"
    payload = {
        "turn_index": max(0, int(turn_index)),
        "history": history,
    }
    ckpt_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
