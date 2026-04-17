import os
from pathlib import Path

from yusuga.config.instruction_system import load_engineered_system_prompt


def load_system_prompt() -> str:
    # 1) Engineered instruction system (preferred)
    workspace_env = os.getenv("YUSUGA_WORKSPACE_ROOT", "").strip()
    workspace_root = Path(workspace_env).resolve() if workspace_env else None
    engineered = load_engineered_system_prompt(workspace_root=workspace_root)
    if engineered.prompt:
        return engineered.prompt

    return ""
