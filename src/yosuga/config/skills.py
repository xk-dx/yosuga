from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


@dataclass(frozen=True)
class SkillMeta:
    slug: str
    name: str
    description: str
    skill_file: Path
    root_dir: Path


class SkillCatalog:
    """Discover skills and load metadata/full content on demand."""

    def __init__(self, workspace_root: Path, project_root: Path):
        self.workspace_root = workspace_root.resolve()
        self.project_root = project_root.resolve()
        self._roots = [
            (self.workspace_root / ".yosuga" / "skills").resolve(),
            (self.project_root / ".yosuga" / "skills").resolve(),
        ]

    def list_meta(self) -> List[SkillMeta]:
        metas: List[SkillMeta] = []
        seen: set[str] = set()

        for root in self._roots:
            if not root.exists() or not root.is_dir():
                continue
            for skill_md in sorted(root.rglob("SKILL.md")):
                skill_dir = skill_md.parent
                slug = skill_dir.name
                if slug.lower() in seen:
                    continue
                name, desc = self._read_yaml_header(skill_md)
                metas.append(
                    SkillMeta(
                        slug=slug,
                        name=name or slug,
                        description=desc or "",
                        skill_file=skill_md,
                        root_dir=skill_dir,
                    )
                )
                seen.add(slug.lower())

        metas.sort(key=lambda x: x.slug.lower())
        return metas

    def load_full(self, skill: str, max_chars: int = 50000) -> Tuple[SkillMeta, str, List[str]]:
        key = (skill or "").strip().lower()
        if not key:
            raise ValueError("skill is required")

        target: SkillMeta | None = None
        for meta in self.list_meta():
            if key in {meta.slug.lower(), meta.name.lower()}:
                target = meta
                break

        if not target:
            raise ValueError(f"Skill not found: {skill}")

        text = target.skill_file.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n... (truncated {len(text) - max_chars} chars)"

        scripts = self._list_scripts(target.root_dir)
        return target, text, scripts

    @staticmethod
    def _read_yaml_header(path: Path) -> Tuple[str, str]:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return "", ""

        name = ""
        desc = ""
        for i in range(1, len(lines)):
            line = lines[i].strip()
            if line == "---":
                break
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            k = k.strip().lower()
            v = v.strip().strip('"').strip("'")
            if k == "name":
                name = v
            elif k == "description":
                desc = v
        return name, desc

    @staticmethod
    def _list_scripts(skill_root: Path) -> List[str]:
        scripts_dir = (skill_root / "scripts").resolve()
        if not scripts_dir.exists() or not scripts_dir.is_dir():
            return []
        out: List[str] = []
        for p in sorted(scripts_dir.rglob("*")):
            if p.is_file():
                out.append(p.relative_to(skill_root).as_posix())
        return out
