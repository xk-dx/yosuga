import argparse
import os
import sys
from pathlib import Path

from yosuga.config.policy import load_policy_rules
from yosuga.config.paths import resolve_runtime_paths
from yosuga.config.session_log import SessionLogger
from yosuga.core.types import ToolCall, ToolPolicyDecision
from yosuga.models.anthropic import load_anthropic_from_env
from yosuga.models.mock import MockModel
from yosuga.models.openai import load_openai_from_env
from yosuga.runtime.kernel import AgentKernel
from yosuga.runtime.report import TurnReportWriter
from yosuga.tools.runtime import build_default_registry


def _print_welcome() -> None:
    width = 64
    print("=" * width)
    print("yosuga Minimal Kernel".center(width))
    print("AI Coding Runtime".center(width))
    print("-" * width)
    print("                     ᡴ ◜ ͡ ͡ ͡ ╮⑅つ")
    print("                     ꒰ ◞ ˔ ◟ ꒱")
    print("                     ╰- ⠀ ⑅ ⠀-╯ ⸝⸝⸝⸝ ) ഒ")
    print("                     ૮ ૮◟ _ ノと⠀ ⠀ ⊹⠀ ྀི")
    print("Commands: /help  |  exit / quit / q")
    print("=" * width)


def _print_runtime_summary(
    project_root: Path,
    workspace_root: Path,
    session_id: str,
    session_log_path: Path,
    session_report_path: Path,
) -> None:
    print("Runtime")
    print(f"  Project root : {project_root}")
    print(f"  Workspace    : {workspace_root}")
    print(f"  Session id   : {session_id}")
    print(f"  Session log  : {session_log_path}")
    print(f"  Session report: {session_report_path}")
    print()


def _event_printer(msg: str) -> None:
    print(msg)


def _approval_prompt(call: ToolCall, decision: ToolPolicyDecision) -> bool:
    print("[policy] Tool call needs confirmation")
    print(f"[policy] tool={call.name}")
    if decision.reason:
        print(f"[policy] reason={decision.reason}")
    if decision.suggestion:
        print(f"[policy] suggestion={decision.suggestion}")
    ans = input("[policy] Continue? [y/N]: ").strip().lower()
    return ans in {"y", "yes"}


def _build_model(backend: str | None = None):
    anthropic_keys = ("ANTHROPIC_API_BASE", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL")
    openai_keys = ("OPENAI_API_KEY", "OPENAI_MODEL")

    if backend == "anthropic":
        try:
            model = load_anthropic_from_env()
            print("Model backend: Anthropic")
            print(f"Model: {os.getenv('ANTHROPIC_MODEL')}")
            return model
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    if backend == "openai":
        try:
            model = load_openai_from_env()
            print("Model backend: OpenAI")
            print(f"Model: {os.getenv('OPENAI_MODEL')}")
            return model
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    if backend == "mock":
        print("Model backend: MockModel")
        return MockModel()

    if all(os.getenv(k, "").strip() for k in anthropic_keys):
        try:
            model = load_anthropic_from_env()
            print("Model backend: Anthropic")
            print(f"Model: {os.getenv('ANTHROPIC_MODEL')}")
            return model
        except Exception as exc:
            print(f"Failed to initialize Anthropic model: {exc}")

    if all(os.getenv(k, "").strip() for k in openai_keys):
        try:
            model = load_openai_from_env()
            print("Model backend: OpenAI")
            print(f"Model: {os.getenv('OPENAI_MODEL')}")
            return model
        except Exception as exc:
            print(f"Failed to initialize OpenAI model: {exc}")

    print("Model backend: MockModel (fallback)")
    print("Usage: python main.py --model [anthropic|openai|mock]")
    return MockModel()


def main() -> None:
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
    args = parser.parse_args()

    _print_welcome()

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    paths = resolve_runtime_paths(workspace_arg=args.workspace)
    os.environ["yosuga_WORKSPACE_ROOT"] = str(paths.workspace_root)
    os.environ["yosuga_PROJECT_ROOT"] = str(paths.project_root)

    policy_rules = load_policy_rules(paths.project_root)
    session_logger = SessionLogger(
        workspace_root=paths.workspace_root,
        relative_dir=policy_rules.session_log_relative_dir,
    )
    report_writer = TurnReportWriter(session_dir=session_logger.session_dir)
    _print_runtime_summary(
        project_root=paths.project_root,
        workspace_root=paths.workspace_root,
        session_id=session_logger.session_id,
        session_log_path=session_logger.path,
        session_report_path=report_writer.path,
    )
    session_logger.log(
        "session_start",
        {
            "project_root": str(paths.project_root),
            "workspace_root": str(paths.workspace_root),
            "model_backend": args.model or "auto",
        },
    )

    history = []
    model = _build_model(backend=args.model)
    tools = build_default_registry(paths.workspace_root)
    kernel = AgentKernel(
        model=model,
        tools=tools,
        approval_hook=_approval_prompt,
        session_logger=session_logger,
        report_writer=report_writer,
    )

    while True:
        try:
            query = input("yosuga> ").strip()
        except (EOFError, KeyboardInterrupt):
            session_logger.log("session_end", {"reason": "keyboard_interrupt_or_eof"})
            print("\nbye")
            break

        if query.lower() in ("q", "quit", "exit"):
            session_logger.log("session_end", {"reason": "user_exit"})
            print("bye")
            break

        if not query:
            continue

        answer = kernel.run_turn(query, history, on_event=_event_printer)
        print(answer)
        print()
