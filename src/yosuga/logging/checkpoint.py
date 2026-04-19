from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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
