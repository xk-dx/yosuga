"""Subagent spawning tool for multi-agent context isolation."""

import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from yosuga.config.instruction_system import load_engineered_system_prompt
from yosuga.config.runtime_config import RuntimeConfig
from yosuga.core.types import ModelResponse, ToolCall, ToolResult
from yosuga.runtime.kernel import AgentKernel
from yosuga.surfaces.cli.app import _event_printer,_approval_prompt
from yosuga.tools.runtime import ToolRegistry

def spawn_subagent(
    task: str,
    role: str = "implementer",
    max_iters: int = 40,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Spawn a subagent with isolated context to execute a task.
    
    The subagent runs its own TAOR loop independently and returns only the final result,
    keeping all intermediate outputs isolated from the parent agent's context.
    
    Args:
        task: The task description for the subagent to execute.
        role: The role for the subagent (e.g., "implementer", "researcher", "reviewer").
        max_iters: Maximum iterations for the subagent's TAOR loop.
        context: Optional additional context to pass to the subagent.
    
    Returns:
        The final result from the subagent as a string.
    """
    # Create runtime config from environment (same way main agent does)
    subagent_config = RuntimeConfig(role=role)
    
    # Load system prompt for the specified role
    system_prompt = load_engineered_system_prompt(
        workspace_root=subagent_config.workspace_root,
        role=role,
    )
    
    # Create model instance for subagent
    model = _create_model(subagent_config, system_prompt.prompt, role)
    
    # Create tool registry for subagent (default tools only, no spawn_subagent)
    # Subagents cannot spawn further subagents to prevent infinite recursion
    tools = subagent_config.create_tools(include_spawn_subagent=False)
    
    # Create subagent kernel
    subagent_kernel = AgentKernel(
        model=model,
        tools=tools,
        max_iters=max_iters,
        approval_hook=_approval_prompt
    )
    
    # Build initial history with context if provided
    history: List[Dict[str, Any]] = []
    if context:
        context_str = "\n".join(f"{k}: {v}" for k, v in context.items())
        full_task = f"Context:\n{context_str}\n\nTask:\n{task}"
    else:
        full_task = task
    
    # Run subagent and get result
    # Propagate subagent events to parent's on_event handler
    def subagent_on_event(event: str) -> None:
        _event_printer(f"[subagent] {event}")
    
    result = subagent_kernel.run_turn(
        user_input=full_task,
        history=history,
        on_event=subagent_on_event,
    )
    print(f"[spawn_subagent] Subagent completed with result: {result}")
    return result


def _create_model(config: RuntimeConfig, system_prompt: str, role: str) -> Any:
    """Create a model instance using RuntimeConfig's create_model method."""
    # Store the system prompt in config temporarily
    config._system_prompt = system_prompt
    return config.create_model(role=role)


# Tool specification for registration
SPAWN_SUBAGENT_SPEC = {
    "name": "spawn_subagent",
    "description": (
        "Spawn a subagent with isolated context to execute a task. "
        "The subagent runs independently with its own TAOR loop and returns only the final result. "
        "Use this to delegate tasks that require separate context isolation from the main agent."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The task description for the subagent to execute.",
            },
            "role": {
                "type": "string",
                "description": "The role for the subagent (e.g., 'implementer', 'researcher', 'reviewer').",
                "enum": ["lead", "implementer", "researcher", "reviewer"],
                "default": "implementer",
            },
            "max_iters": {
                "type": "integer",
                "description": "Maximum iterations for the subagent's TAOR loop.",
                "default": 40,
            },
            "context": {
                "type": "object",
                "description": "Optional additional context to pass to the subagent.",
            },
        },
        "required": ["task"],
    },
}


def create_spawn_subagent_handler(parent_config: RuntimeConfig) -> Callable[..., str]:
    """
    Create a spawn_subagent handler bound to a parent agent's configuration.
    
    This factory function allows the subagent tool to inherit settings from the parent
    while running with isolated context.
    
    Args:
        parent_config: The RuntimeConfig of the parent agent.
    
    Returns:
        A callable that spawns a subagent with the given configuration.
    """
    def handler(
        task: str,
        role: str = "implementer",
        max_iters: int = 40,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        return spawn_subagent(
            task=task,
            role=role,
            max_iters=max_iters,
            context=context,
        )
    return handler
