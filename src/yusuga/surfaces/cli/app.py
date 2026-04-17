import argparse
import os
import sys
from pathlib import Path

from yusuga.config.paths import resolve_runtime_paths
from yusuga.models.anthropic import load_anthropic_from_env
from yusuga.models.mock import MockModel
from yusuga.models.openai import load_openai_from_env
from yusuga.runtime.kernel import AgentKernel
from yusuga.tools.runtime import build_default_registry


def _event_printer(msg: str) -> None:
    print(msg)


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
    parser = argparse.ArgumentParser(description="Yusuga Agent Kernel")
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

    print("ᡴ ◜ ͡ ͡ ͡ ╮⑅つ")
    print("꒰ ◞ ˔ ◟ ꒱")
    print("╰- ⠀ ⑅ ⠀-╯ ⸝⸝⸝⸝ ) ഒ")
    print("૮ ૮◟ _ ノと⠀ ⠀ ⊹⠀ ྀི")
    print("Yusuga Minimal Kernel")
    print("Type /help for commands. Type exit to quit.")

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    paths = resolve_runtime_paths(workspace_arg=args.workspace)
    os.environ["YUSUGA_WORKSPACE_ROOT"] = str(paths.workspace_root)
    os.environ["YUSUGA_PROJECT_ROOT"] = str(paths.project_root)

    print(f"Project root: {paths.project_root}")
    print(f"Workspace root: {paths.workspace_root}")

    history = []
    model = _build_model(backend=args.model)
    tools = build_default_registry(paths.workspace_root)
    kernel = AgentKernel(model=model, tools=tools)

    while True:
        try:
            query = input("yusuga> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break

        if query.lower() in ("q", "quit", "exit"):
            print("bye")
            break

        if not query:
            continue

        answer = kernel.run_turn(query, history, on_event=_event_printer)
        print(answer)
        print()
