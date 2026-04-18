# yosuga

`yosuga` is a minimal AI coding runtime for the workspace in this repository. It provides a CLI agent loop, model backends, tool execution, policy control, session logging, turn reports, and a skills system that injects metadata into the system prompt.

中文说明请见 [README.zh.md](README.zh.md).

## What It Does

- Starts an interactive CLI agent from the workspace root.
- Supports OpenAI-compatible, Anthropic-compatible, and mock model backends.
- Executes workspace tools such as `read_file`, `write_file`, `edit_file`, `list_dir`, `bash`, `list_skills`, and `use_skill`.
- Applies tool policy checks, approval prompts, retry handling, and circuit breaking.
- Writes session logs and per-turn reports to separate files.
- Loads engineered system instructions plus skills metadata at startup.

## Project Layout

- `main.py` - entry point for local execution.
- `src/yosuga/surfaces/cli/app.py` - CLI bootstrap and interactive loop.
- `src/yosuga/runtime/kernel.py` - turn orchestration, tool dispatch, and reporting.
- `src/yosuga/models/` - model adapters for OpenAI, Anthropic, and mock backends.
- `src/yosuga/tools/runtime.py` - default tool registry.
- `src/yosuga/config/` - runtime paths, policy, session logging, skills, and system prompt composition.
- `src/yosuga/runtime/report.py` - turn report writer.

## Quick Start

Run the CLI from the repository root:

```bash
python main.py
```

You can also select a backend explicitly:

```bash
python main.py --model mock
python main.py --model openai
python main.py --model anthropic
```

If `--model` is omitted, the launcher tries to auto-detect configured environment variables and falls back to the mock model.

## Workspace Option

By default, the current directory is treated as the workspace root. You can override it:

```bash
python main.py --workspace e:\projects\ai_project\some-workspace
```

The workspace root is the directory the tools operate on.

## Environment Variables

The runtime reads the following environment variables when available:

selectable
- `yosuga_WORKSPACE_ROOT` - workspace root used by the prompt builder and runtime.
- `yosuga_PROJECT_ROOT` - project root used for policy and prompt assets.
- `AGENT_ROLE` - role used when loading instruction assets.

necessary
- `OPENAI_API_BASE` - OpenAI-compatible API base URL.
- `OPENAI_API_KEY` - OpenAI-compatible backend key.
- `OPENAI_MODEL` - OpenAI-compatible model name.
- `ANTHROPIC_API_BASE` - Anthropic API base URL.
- `ANTHROPIC_API_KEY` - Anthropic API key.
- `ANTHROPIC_MODEL` - Anthropic model name.

The launcher will call `python-dotenv` if it is installed, so a local `.env` file can be used.

## Skills System

The system prompt includes a metadata-only skills index from `.yosuga/skills`. At runtime:

1. The prompt includes a compact skills index.
2. The model can call `list_skills` to enumerate available skills.
3. The model can call `use_skill` to load the full `SKILL.md` content for a specific skill.
4. Skills may expose runnable scripts that can be executed through the normal tool loop.

This keeps startup context small while still making the full skill content available on demand.

## Logging and Reports

Each session gets its own directory containing:

- `session.jsonl` for session events.
- `report.jsonl` for per-turn metrics.

The report currently tracks model calls, token usage, tool success and failure counts, retry counts, and model-side tool-argument validation errors.

## Policy and Safety

Tool calls are filtered through policy rules before execution. Some calls may require user approval, and repeated tool failures can temporarily open a circuit breaker for that tool.

## Status

The codebase is usable as a working CLI agent runtime, but it is still evolving.

### Completed

- Interactive CLI loop.
- Model adapters for Anthropic, OpenAI-compatible, and mock backends.
- Tool registry with file, directory, shell, and skills tools.
- Policy checks, approval prompts, retries, and circuit breaking.
- Session logging and per-turn reporting.
- System prompt composition with skills metadata injection.

### Unfinished / In Progress

- Memory system (planned):
	- Add persistent memory scopes (user/session/repo) with retrieval and write-back policies.
	- Integrate memory recall into turn planning and system prompt assembly.
	- Add memory safety rules (redaction, size limits, conflict handling).
- Multi-agent system (planned):
	- Add coordinator-worker orchestration for decomposition and parallel task execution.
	- Define agent roles, handoff protocol, and shared context contract.
	- Add aggregation and conflict resolution for multi-agent outputs.

## Notes

- The workspace is intended to stay writable only within the configured workspace root.
- The project name used in code and runtime output is `yosuga`.
