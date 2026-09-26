"""Verification strategy abstraction (Phase 9).

Defines:
- BaseVerificationStrategy: Abstract base class for all deterministic post-execution verifiers.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.models.execution import ExecutionStepResult
from app.models.execution_plan import PlannedStep
from app.models.verification import (
    VerificationCheck,
    VerificationStrategyType,
)


class BaseVerificationStrategy(ABC):
    """Abstract base class for deterministic verification strategies."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the verification strategy."""
        pass

    @property
    @abstractmethod
    def strategy_type(self) -> VerificationStrategyType:
        """Strategy type enum."""
        pass

    @abstractmethod
    def supports(self, step: PlannedStep, step_result: ExecutionStepResult) -> bool:
        """Determines if this verifier can evaluate the executed step."""
        pass

    @abstractmethod
    def build_checks(
        self,
        execution_id: str,
        step: PlannedStep,
        step_result: ExecutionStepResult,
        sandbox_root: str,
        custom_expectations: Optional[Dict[str, Any]] = None,
    ) -> List[VerificationCheck]:
        """Constructs one or more atomic VerificationCheck objects from the planned/executed step."""
        pass

    @abstractmethod
    def verify(
        self,
        check: VerificationCheck,
        sandbox_root: str,
    ) -> VerificationCheck:
        """Evaluates an individual VerificationCheck deterministically and populates actual_state, status, and evidence."""
        pass
