from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    project_root: Path
    workspace_root: Path


def default_project_root() -> Path:
    # src/yusuga/config/paths.py -> src/yusuga
    return Path(__file__).resolve().parents[1]


def resolve_runtime_paths(workspace_arg: str | None = None) -> RuntimePaths:
    project_root = default_project_root()

    env_workspace = os.getenv("YUSUGA_WORKSPACE_ROOT", "").strip()
    raw_workspace = workspace_arg or env_workspace
    if raw_workspace:
        workspace_root = Path(raw_workspace).resolve()
    else:
        workspace_root = Path.cwd().resolve()

    return RuntimePaths(project_root=project_root, workspace_root=workspace_root)
