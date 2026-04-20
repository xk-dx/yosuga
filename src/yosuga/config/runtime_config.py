"""
Runtime configuration and initialization manager for yosuga agents.

This module provides unified configuration and initialization logic to reduce coupling
between CLI and business logic, making it easier to support multi-agent scenarios.
"""
import os
from pathlib import Path
from typing import Any, Optional

from yosuga.config.instruction_system import load_engineered_system_prompt
from yosuga.config.paths import resolve_runtime_paths, RuntimePaths
from yosuga.config.policy import load_policy_rules, PolicyRules
from yosuga.config.skills import SkillCatalog
from yosuga.logging import RuntimeLogger
from yosuga.runtime.report import TurnReportWriter
from yosuga.tools.runtime import build_default_registry, ToolRegistry


class RuntimeConfig:
    """
    Unified runtime configuration that manages all initialization dependencies.

    This class encapsulates the creation and management of:
    - Path resolution
    - Policy rules
    - Model backends
    - Tool registries
    - Logging and reporting
    - System prompts
    """

    def __init__(
        self,
        workspace_root: Optional[Path] = None,
        project_root: Optional[Path] = None,
        model_backend: Optional[str] = None,
        role: str = "lead"
    ):
        # Path resolution
        if workspace_root:
            os.environ["yosuga_WORKSPACE_ROOT"] = str(workspace_root)
        if project_root:
            os.environ["yosuga_PROJECT_ROOT"] = str(project_root)

        self.paths = resolve_runtime_paths(workspace_arg=str(workspace_root) if workspace_root else None)
        self.role = role
        self.model_backend = model_backend

        # Load configuration
        self.policy_rules = load_policy_rules(self.paths.project_root)

        # Initialize components lazily
        self._model = None
        self._tools = None
        self._logger = None
        self._report_writer = None
        self._system_prompt = None
        self._session_id = None

    @property
    def workspace_root(self) -> Path:
        """Get workspace root path."""
        return self.paths.workspace_root

    @property
    def project_root(self) -> Path:
        """Get project root path."""
        return self.paths.project_root

    @property
    def state_root(self) -> Path:
        """Get state root path."""
        return self.paths.state_root

    def create_model(self, role: Optional[str] = None) -> Any:
        """
        Create model instance based on backend and role.

        Args:
            role: Override the default role for this model

        Returns:
            Model instance (AnthropicModel, OpenAIModel, or MockModel)
        """
        from yosuga.models.anthropic import load_anthropic_from_env
        from yosuga.models.openai import load_openai_from_env
        from yosuga.models.mock import MockModel

        effective_role = role or self.role
        backend = self.model_backend

        # Explicit backend selection
        if backend == "anthropic":
            try:
                return load_anthropic_from_env(workspace_root=self.workspace_root, role=effective_role)
            except Exception as exc:
                raise RuntimeError(f"Failed to initialize Anthropic model: {exc}") from exc

        elif backend == "openai":
            try:
                return load_openai_from_env(workspace_root=self.workspace_root, role=effective_role)
            except Exception as exc:
                raise RuntimeError(f"Failed to initialize OpenAI model: {exc}") from exc

        elif backend == "mock":
            return MockModel()

        # Auto-detect from environment
        anthropic_keys = ("ANTHROPIC_API_BASE", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL")
        if all(os.getenv(k, "").strip() for k in anthropic_keys):
            try:
                return load_anthropic_from_env(workspace_root=self.workspace_root, role=effective_role)
            except Exception as exc:
                raise RuntimeError(f"Failed to initialize Anthropic model: {exc}") from exc

        openai_keys = ("OPENAI_API_KEY", "OPENAI_MODEL")
        if all(os.getenv(k, "").strip() for k in openai_keys):
            try:
                return load_openai_from_env(workspace_root=self.workspace_root, role=effective_role)
            except Exception as exc:
                raise RuntimeError(f"Failed to initialize OpenAI model: {exc}") from exc

        # Fallback to mock
        return MockModel()

    def create_tools(self) -> ToolRegistry:
        """
        Create tool registry with workspace and policy configuration.

        Returns:
            Configured ToolRegistry instance
        """
        return build_default_registry(
            root=self.workspace_root,
            state_root=self.state_root
        )

    def create_logger(self, session_id: Optional[str] = None) -> RuntimeLogger:
        """
        Create runtime logger for session tracking.

        Args:
            session_id: Existing session ID to resume, or None for new session

        Returns:
            RuntimeLogger instance
        """
        self._session_id = session_id
        return RuntimeLogger(
            state_root=self.state_root,
            relative_dir=self.policy_rules.session_log_relative_dir,
            session_id=session_id or None,
        )

    def create_report_writer(self, session_dir: Path) -> TurnReportWriter:
        """
        Create turn report writer for metrics collection.

        Args:
            session_dir: Session directory path

        Returns:
            TurnReportWriter instance
        """
        return TurnReportWriter(session_dir=session_dir)

    def load_system_prompt(self, role: Optional[str] = None) -> str:
        """
        Load system prompt for specified role.

        Args:
            role: Role to load prompt for, defaults to config role

        Returns:
            System prompt string
        """
        effective_role = role or self.role
        prompt = load_engineered_system_prompt(
            workspace_root=self.workspace_root,
            role=effective_role
        )
        self._system_prompt = prompt.prompt
        return self._system_prompt

    def switch_role(self, new_role: str) -> None:
        """
        Switch the default role for subsequent operations.

        Args:
            new_role: New role to use
        """
        self.role = new_role
        self._system_prompt = None  # Invalidate cached prompt

    def get_skill_catalog(self) -> SkillCatalog:
        """
        Get skill catalog for the workspace.

        Returns:
            SkillCatalog instance
        """
        return SkillCatalog(
            workspace_root=self.workspace_root,
            project_root=self.project_root
        )

    def create_agent_components(
        self,
        session_id: Optional[str] = None,
        approval_hook=None,
        logger: Optional[RuntimeLogger] = None
    ) -> tuple:
        """
        Create all components needed for an agent instance.

        This is a convenience method that creates model, tools, logger, and
        report writer in a single call, which is useful for multi-agent scenarios.

        Args:
            session_id: Optional session ID to resume
            approval_hook: Optional approval callback for tool calls
            logger: Optional existing logger (creates new one if None)

        Returns:
            Tuple of (model, tools, logger, report_writer)
        """
        model = self.create_model()
        tools = self.create_tools()

        if logger is None:
            logger = self.create_logger(session_id=session_id)

        report_writer = self.create_report_writer(logger.session_dir)

        return model, tools, logger, report_writer

    def get_model_info(self) -> dict:
        """
        Get information about the current model configuration.

        Returns:
            Dictionary with model backend and name info
        """
        backend = self.model_backend or "auto-detect"

        if backend == "anthropic":
            return {
                "backend": "anthropic",
                "model": os.getenv("ANTHROPIC_MODEL", "unknown")
            }
        elif backend == "openai":
            return {
                "backend": "openai",
                "model": os.getenv("OPENAI_MODEL", "unknown")
            }
        elif backend == "mock":
            return {
                "backend": "mock",
                "model": "MockModel"
            }
        else:
            # Auto-detect
            if all(os.getenv(k, "").strip() for k in ("ANTHROPIC_API_BASE", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL")):
                return {
                    "backend": "anthropic",
                    "model": os.getenv("ANTHROPIC_MODEL", "unknown")
                }
            elif all(os.getenv(k, "").strip() for k in ("OPENAI_API_KEY", "OPENAI_MODEL")):
                return {
                    "backend": "openai",
                    "model": os.getenv("OPENAI_MODEL", "unknown")
                }
            else:
                return {
                    "backend": "mock",
                    "model": "MockModel (fallback)"
                }