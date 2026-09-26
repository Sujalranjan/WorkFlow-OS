"""Executor abstraction and interfaces for WorkFlowOS (Phase 8).

Defines:
- BaseExecutor: Abstract base class for all execution strategy engines.
"""

from abc import ABC, abstractmethod
from typing import List, Tuple

from app.models.execution import ExecutionContext, ExecutionStepResult
from app.models.execution_plan import ExecutionStrategy, PlannedStep
from app.models.strategy import ExecutionStrategyType, ExecutorCapability


class BaseExecutor(ABC):
    """Abstract base class representing an execution strategy engine."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier name for this executor."""
        pass

    @property
    @abstractmethod
    def capability(self) -> ExecutorCapability:
        """Deterministic capability metadata exposed by this executor."""
        pass


    @abstractmethod
    def supports(self, strategy: ExecutionStrategy) -> bool:
        """Determines if this executor handles the requested strategy."""
        pass

    @abstractmethod
    def validate(self, step: PlannedStep, context: ExecutionContext) -> Tuple[bool, List[str]]:
        """Validates that the planned step conforms to executor guardrails before execution.

        Returns:
            Tuple[bool, List[str]]: (is_valid, list_of_validation_error_messages)
        """
        pass

    @abstractmethod
    def execute(self, step: PlannedStep, context: ExecutionContext) -> ExecutionStepResult:
        """Executes a single planned step and returns a structured ExecutionStepResult."""
        pass
