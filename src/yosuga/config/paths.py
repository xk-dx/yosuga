from __future__ import annotations

import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    project_root: Path
    workspace_root: Path
    state_root: Path


def default_project_root() -> Path:
    # src/yosuga/config/paths.py -> src/yosuga
    return Path(__file__).resolve().parents[1]


def default_repository_root() -> Path:
    # src/yosuga/config/paths.py -> repo root
    return Path(__file__).resolve().parents[3]


def resolve_runtime_paths(workspace_arg: str | None = None) -> RuntimePaths:
    project_root = default_project_root()
    repository_root = default_repository_root()

    env_workspace = os.getenv("yosuga_WORKSPACE_ROOT", "").strip()
    raw_workspace = workspace_arg or env_workspace
    if raw_workspace:
        workspace_root = Path(raw_workspace).resolve()
    else:
        workspace_root = Path.cwd().resolve()

    normalized_workspace = str(workspace_root).replace("\\", "/").lower()
    project_hash = sha256(normalized_workspace.encode("utf-8")).hexdigest()[:16]
    state_root = (repository_root / ".yosuga" / "projects" / project_hash / "session").resolve()

    return RuntimePaths(project_root=project_root, workspace_root=workspace_root, state_root=state_root)
