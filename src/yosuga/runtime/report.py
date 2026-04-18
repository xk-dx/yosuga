import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class TurnReportWriter:
    def __init__(self, session_dir: Path):
        self._path = (session_dir / "report.jsonl").resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def write_turn(self, payload: Dict[str, Any]) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_type": "turn_report",
            "payload": payload,
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
