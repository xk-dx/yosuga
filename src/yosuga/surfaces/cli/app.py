import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from yosuga.config.runtime_config import RuntimeConfig
from yosuga.logging import find_latest_session_id, load_history_ckpt, save_history_ckpt
from yosuga.core.types import ToolCall, ToolPolicyDecision
from yosuga.runtime.kernel import AgentKernel


class _Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"


_COLOR_ENABLED = False


def _init_color() -> None:
    global _COLOR_ENABLED
    if not sys.stdout.isatty():
        _COLOR_ENABLED = False
        return

    # Best effort on Windows terminals; safe no-op elsewhere.
    try:
        from colorama import just_fix_windows_console

        just_fix_windows_console()
    except Exception:
        pass

    _COLOR_ENABLED = True


def _paint(text: str, color: str) -> str:
    if not _COLOR_ENABLED:
        return text
    return f"{color}{text}{_Color.RESET}"


def _print_welcome() -> None:
    width = 64
    print(_paint("=" * width, _Color.CYAN))
    print(_paint("yosuga Minimal Kernel".center(width), _Color.BOLD + _Color.CYAN))
    print(_paint("AI Coding Runtime".center(width), _Color.CYAN))
    print(_paint("-" * width, _Color.CYAN))
    print("                     ᡴ ◜ ͡ ͡ ͡ ╮⑅つ")
    print("                     ꒰ ◞ ˔ ◟ ꒱")
    print("                     ╰- ⠀ ⑅ ⠀-╯ ⸝⸝⸝⸝ ) ഒ")
    print("                     ૮ ૮◟ _ ノと⠀ ⠀ ⊹⠀ ྀི")
    print(_paint("Commands: /help  |  /mutate [allow|confirm|block]  |  exit / quit / q", _Color.DIM))
    print(_paint("=" * width, _Color.CYAN))


def _print_help() -> None:
    print(_paint("Commands", _Color.BOLD + _Color.BLUE))
    print(_paint("  /help                           Show this help", _Color.BLUE))
    print(_paint("  /mutate allow                   Allow write/edit without prompt", _Color.BLUE))
    print(_paint("  /mutate confirm                 Require approval before write/edit", _Color.BLUE))
    print(_paint("  /mutate block                   Block write/edit", _Color.BLUE))
    print(_paint("  /role <name>                    Switch session role instructions", _Color.BLUE))
    print(_paint("  exit | quit | q                 Exit", _Color.BLUE))
    print()


def _print_runtime_summary(
    project_root: Path,
    workspace_root: Path,
    session_id: str,
    session_log_path: Path,
    session_report_path: Path,
    config: Optional["RuntimeConfig"] = None,
) -> None:
    print(_paint("Runtime", _Color.BOLD + _Color.BLUE))
    print(_paint(f"  Project root : {project_root}", _Color.BLUE))
    print(_paint(f"  Workspace    : {workspace_root}", _Color.BLUE))
    print(_paint(f"  Session id   : {session_id}", _Color.BLUE))
    print(_paint(f"  Session log  : {session_log_path}", _Color.BLUE))
    print(_paint(f"  Session report: {session_report_path}", _Color.BLUE))
    print()


def _event_printer(msg: str) -> None:
    if msg.startswith("[tool]"):
        print(_paint(msg, _Color.YELLOW))
        return
    if msg.startswith("[model"):
        print(_paint(msg, _Color.CYAN))
        return
    if msg.startswith("[policy]"):
        print(_paint(msg, _Color.MAGENTA))
        return
    print(msg)


def _approval_prompt(call: ToolCall, decision: ToolPolicyDecision) -> str:
    print(_paint("[policy] Tool call needs confirmation", _Color.MAGENTA))
    print(_paint(f"[policy] tool={call.name}", _Color.MAGENTA))
    if decision.reason:
        print(_paint(f"[policy] reason={decision.reason}", _Color.MAGENTA))
    if decision.suggestion:
        print(_paint(f"[policy] suggestion={decision.suggestion}", _Color.MAGENTA))
    ans = input(_paint("[policy] Continue? [y/N]: ", _Color.BOLD + _Color.MAGENTA)).strip().lower()
    if ans in {"y", "yes"}:
        return ""

    reason = input(_paint("[policy] Rejection reason (optional): ", _Color.BOLD + _Color.MAGENTA)).strip()
    if reason:
        return reason

    command_hint = "Rejected by user."
    print(_paint(f"[policy] {command_hint}", _Color.MAGENTA))
    return command_hint


def _build_model(config: RuntimeConfig, backend: str | None = None):
    """Build model using RuntimeConfig for unified initialization."""
    effective_backend = backend or config.model_backend

    try:
        model = config.create_model()
        model_info = config.get_model_info()
        print(_paint(f"Model backend: {model_info['backend'].capitalize()}", _Color.GREEN))
        print(_paint(f"Model: {model_info['model']}", _Color.GREEN))
        return model
    except Exception as exc:
        print(_paint(f"Error: {exc}", _Color.RED), file=sys.stderr)
        sys.exit(1)


def main() -> None:
    _init_color()
    parser = argparse.ArgumentParser(description="yosuga Agent Kernel")
    parser.add_argument(
        "--model",
        choices=["anthropic", "openai", "mock"],
        default=None,
        help="Model backend: anthropic, openai, or mock (default: auto-detect from env)",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help="Working code directory for tool operations (default: current directory)",
    )
    parser.add_argument(
        "--resume",
        default="",
        help="Resume from history checkpoint: latest or explicit session id",
    )
    args = parser.parse_args()

    _print_welcome()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    # Use RuntimeConfig for unified initialization
    config = RuntimeConfig(
        workspace_root=Path(args.workspace) if args.workspace else None,
        model_backend=args.model,
        role="lead"
    )

    # Handle session resume
    resume_arg = (args.resume or "").strip()
    resume_session_id = ""
    if resume_arg:
        if resume_arg.lower() == "latest":
            resume_session_id = find_latest_session_id(config.state_root, config.policy_rules.session_log_relative_dir) or ""
        else:
            resume_session_id = resume_arg

    # Create components using RuntimeConfig
    session_logger = config.create_logger(session_id=resume_session_id or None)
    report_writer = config.create_report_writer(session_logger.session_dir)

    _print_runtime_summary(
        project_root=config.project_root,
        workspace_root=config.workspace_root,
        session_id=session_logger.session_id,
        session_log_path=session_logger.path,
        session_report_path=report_writer.path,
    )
    session_logger.log(
        "session_start",
        {
            "project_root": str(config.project_root),
            "workspace_root": str(config.workspace_root),
            "model_backend": args.model or "auto",
        },
    )

    history = []
    recovered_turn_index = 0
    if resume_arg:
        history, recovered_turn_index = load_history_ckpt(session_logger.session_dir)
        if history:
            print(_paint(f"Recovered checkpoint: {len(history)} messages from session {session_logger.session_id}", _Color.YELLOW))
        else:
            print(_paint(f"Resume requested but no history.ckpt.json found for session {session_logger.session_id}", _Color.YELLOW))

    # Create model and tools using RuntimeConfig
    current_role = "lead"
    model = _build_model(config, backend=args.model)
    # Create tools with spawn_subagent enabled for the main agent
    tools = config.create_tools(include_spawn_subagent=True)

    kernel = AgentKernel(
        model=model,
        tools=tools,
        approval_hook=_approval_prompt,
        logger=session_logger,
        report_writer=report_writer,
    )
    if recovered_turn_index > 0:
        kernel.set_turn_index(recovered_turn_index)

    print(_paint(f"Mutation mode: {tools.get_mutation_mode()}", _Color.DIM))

    while True:
        try:
            query = input(_paint("yosuga> ", _Color.BOLD + _Color.CYAN)).strip()
        except (EOFError, KeyboardInterrupt):
            session_logger.log("session_end", {"reason": "keyboard_interrupt_or_eof"})
            print(_paint("\nbye", _Color.DIM))
            break

        if query.lower() in ("q", "quit", "exit"):
            session_logger.log("session_end", {"reason": "user_exit"})
            print(_paint("bye", _Color.DIM))
            break

        if query.startswith("/"):
            cmd = query.strip()
            if cmd == "/help":
                _print_help()
                continue

            if cmd.startswith("/mutate"):
                parts = cmd.split()
                if len(parts) != 2:
                    print(_paint("Usage: /mutate [allow|confirm|block]", _Color.YELLOW))
                    continue
                mode = parts[1].strip().lower()
                try:
                    tools.set_mutation_mode(mode)
                    print(_paint(f"Mutation mode set to: {tools.get_mutation_mode()}", _Color.YELLOW))
                except ValueError as exc:
                    print(_paint(str(exc), _Color.RED))
                continue

            if cmd.startswith("/role"):
                parts = cmd.split(maxsplit=1)
                if len(parts) != 2 or not parts[1].strip():
                    print(_paint("Usage: /role <name>", _Color.YELLOW))
                    continue
                new_role = parts[1].strip().lower()
                try:
                    config.switch_role(new_role)
                    prompt = config.load_system_prompt(new_role)
                    if hasattr(model, "system_prompt"):
                        model.system_prompt = prompt
                    current_role = new_role
                    print(_paint(f"Role switched to: {current_role}", _Color.YELLOW))
                except Exception as exc:
                    print(_paint(f"Failed to switch role: {exc}", _Color.RED))
                continue

            print(_paint("Unknown command. Use /help", _Color.YELLOW))
            continue

        if not query:
            continue

        answer = kernel.run_turn(query, history, on_event=_event_printer)
        save_history_ckpt(session_logger.session_dir, history, kernel.get_turn_index())
        print(_paint(answer, _Color.GREEN))
        print()
