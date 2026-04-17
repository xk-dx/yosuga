# YUSUGA Project Policy

## Scope
- This workspace focuses on building an engineering-grade coding agent harness.
- Preserve the capability-domain architecture under src/yusuga.

## Architecture Rules
- Keep modules focused: runtime, models, tools, config, surfaces.
- Avoid cross-layer shortcuts that bypass module boundaries.

## Code Change Rules
- Prefer minimal, targeted changes.
- Preserve existing behavior unless explicitly changed.
- Validate critical paths after edits.

## Tooling and Safety
- Block destructive operations by default.
- Do not expose secrets in logs or user-visible output.

## Collaboration
- Role behavior should be declared in instruction role cards.
- Any new role must define responsibilities and non-goals.
