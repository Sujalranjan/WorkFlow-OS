"""Verification Strategy Registry (Phase 9).

Maintains available verification strategies and resolves verifiers for planned steps.
"""

from typing import Dict, List, Optional

from app.models.execution import ExecutionStepResult
from app.models.execution_plan import PlannedStep
from app.models.verification import VerificationStrategyType
from app.services.verifiers.base import BaseVerificationStrategy
from app.services.verifiers.file_system import FileSystemVerificationStrategy
from app.services.verifiers.gmail_verifier import GmailVerificationStrategy
from app.services.verifiers.structured_output import StructuredOutputVerificationStrategy


class VerificationStrategyRegistry:
    """Registry maintaining active verification strategies."""

    def __init__(self) -> None:
        self._strategies: Dict[str, BaseVerificationStrategy] = {}
        # Register default verification strategies (Phase 9 & Phase 12)
        self.register(FileSystemVerificationStrategy())
        self.register(StructuredOutputVerificationStrategy())
        self.register(GmailVerificationStrategy())

    def register(self, strategy: BaseVerificationStrategy) -> None:
        """Registers a verification strategy instance."""
        self._strategies[strategy.name] = strategy

    def get_strategies_for_step(
        self,
        step: PlannedStep,
        step_result: ExecutionStepResult,
    ) -> List[BaseVerificationStrategy]:
        """Finds all verification strategies supporting the step."""
        matched = []
        for strategy in self._strategies.values():
            if strategy.supports(step, step_result):
                matched.append(strategy)
        return matched

    def get_by_name(self, name: str) -> Optional[BaseVerificationStrategy]:
        """Retrieves a strategy by its unique name."""
        return self._strategies.get(name)

    def list_strategies(self) -> List[str]:
        """Lists registered strategy names."""
        return list(self._strategies.keys())
