from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import List, Tuple

from yosuga.config.paths import default_project_root
from yosuga.config.skills import SkillCatalog


@dataclass
class PromptBuildResult:
    prompt: str
    fixed_prefix: str
    prompt_hash: str
    sources: List[str]


class InstructionComposer:
    """Compose system prompt from engineering instruction assets."""

    CORE_ORDER = ["identity", "behavior", "tooling", "tone", "safety"]

    def __init__(self, project_root: Path, workspace_root: Path, role: str = "lead"):
        self.project_root = project_root
        self.workspace_root = workspace_root
        self.role = role.strip().lower() or "lead"
        self.instructions_root = self.project_root / "instructions"

    def compose(self) -> PromptBuildResult:
        blocks: List[str] = []
        sources: List[str] = []

        core_blocks, core_sources = self._load_core_blocks()
        blocks.extend(core_blocks)
        sources.extend(core_sources)

        role_block, role_source = self._load_role_block(self.role)
        if role_block:
            blocks.append(role_block)
            sources.append(role_source)

        project_block, project_source = self._load_project_policy()
        if project_block:
            blocks.append(project_block)
            sources.append(project_source)

        workspace_block, workspace_source = self._load_workspace_policy()
        if workspace_block:
            blocks.append(workspace_block)
            sources.append(workspace_source)

        runtime_block = self._build_runtime_workspace_block()
        if runtime_block:
            blocks.append(runtime_block)
            sources.append("runtime:workspace-root")

        skill_index_block, skill_index_source = self._build_skill_index_block()
        if skill_index_block:
            blocks.append(skill_index_block)
            sources.append(skill_index_source)

        fixed_prefix = "\n\n".join(blocks).strip()
        prompt_hash = sha256(fixed_prefix.encode("utf-8")).hexdigest() if fixed_prefix else ""
        return PromptBuildResult(
            prompt=fixed_prefix,
            fixed_prefix=fixed_prefix,
            prompt_hash=prompt_hash,
            sources=sources,
        )

    def _load_core_blocks(self) -> Tuple[List[str], List[str]]:
        blocks: List[str] = []
        sources: List[str] = []
        for name in self.CORE_ORDER:
            path = self.instructions_root / "core" / f"{name}.md"
            text = self._read_text_if_exists(path)
            if text:
                blocks.append(text)
                sources.append(str(path))
        return blocks, sources

    def _load_role_block(self, role: str) -> Tuple[str, str]:
        path = self.instructions_root / "roles" / f"{role}.md"
        text = self._read_text_if_exists(path)
        if text:
            return text, str(path)

        fallback = self.instructions_root / "roles" / "lead.md"
        fallback_text = self._read_text_if_exists(fallback)
        return fallback_text, str(fallback) if fallback_text else ""

    def _load_project_policy(self) -> Tuple[str, str]:
        path = self.project_root / "YOSUGA.md"
        text = self._read_text_if_exists(path)
        return (text, str(path)) if text else ("", "")

    def _load_workspace_policy(self) -> Tuple[str, str]:
        # Workspace policy is similar to CLAUDE.md semantics: repo-local behavior rules.
        candidates = [
            self.workspace_root / "yosuga.md",
            self.workspace_root / "YOSUGA.md",
            self.workspace_root / "CLAUDE.md",
        ]

        project_policy_path = (self.project_root / "yosuga.md").resolve()
        for path in candidates:
            if not path.exists() or not path.is_file():
                continue

            resolved = path.resolve()
            if resolved == project_policy_path:
                continue

            text = self._read_text_if_exists(path)
            if text:
                header = "# Workspace Policy (from workspace_root)\n\n"
                return (header + text, str(path))

        return ("", "")

    def _build_runtime_workspace_block(self) -> str:
        shell = os.getenv("SHELL") or os.getenv("ComSpec") or "unknown"
        os_name = os.name
        platform_name = platform.platform()
        python_version = sys.version.split()[0]
        path_sep = os.sep
        is_windows = os_name == "nt"
        command_hint = (
            "Use Windows-compatible commands (PowerShell/cmd), avoid bash-specific syntax like brace expansion."
            if is_windows
            else "Use POSIX-compatible shell commands."
        )

        return (
            "# Runtime Workspace\n\n"
            f"- project_root: {self.project_root}\n"
            f"- workspace_root: {self.workspace_root}\n"
            f"- os_name: {os_name}\n"
            f"- platform: {platform_name}\n"
            f"- python_version: {python_version}\n"
            f"- shell: {shell}\n"
            f"- path_separator: {path_sep}\n"
            "- Use workspace_root as the only writable code area for tool operations.\n"
            f"- {command_hint}"
        )

    def _build_skill_index_block(self) -> Tuple[str, str]:
        catalog = SkillCatalog(workspace_root=self.workspace_root, project_root=self.project_root)
        metas = catalog.list_meta()
        if not metas:
            return "", ""

        lines = [
            "# Skills Index (metadata-only)",
            "",
            "Only metadata is preloaded at startup. Use tool `use_skill` to load a full skill when needed.",
            "",
        ]
        for meta in metas[:120]:
            desc = meta.description.strip().replace("\n", " ")
            if len(desc) > 180:
                desc = desc[:180] + "..."
            lines.append(f"- slug: {meta.slug} | name: {meta.name} | description: {desc}")

        if len(metas) > 120:
            lines.append(f"- ... ({len(metas) - 120} more skills)")

        return "\n".join(lines), "runtime:skills-index"

    @staticmethod
    def _read_text_if_exists(path: Path) -> str:
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip()


def load_engineered_system_prompt(workspace_root: Path | None = None) -> PromptBuildResult:
    project_root = default_project_root()
    resolved_workspace = workspace_root or Path(os.getenv("yosuga_WORKSPACE_ROOT", "") or Path.cwd())
    resolved_workspace = resolved_workspace.resolve()
    role = os.getenv("AGENT_ROLE", "lead")
    composer = InstructionComposer(
        project_root=project_root,
        workspace_root=resolved_workspace,
        role=role,
    )
    return composer.compose()


def load_system_prompt() -> str:
    workspace_env = os.getenv("yosuga_WORKSPACE_ROOT", "").strip()
    workspace_root = Path(workspace_env).resolve() if workspace_env else None
    engineered = load_engineered_system_prompt(workspace_root=workspace_root)
    return engineered.prompt or ""
