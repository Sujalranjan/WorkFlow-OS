"""Building blocks every integration declares.

An `Integration` describes one external tool in a single place:
- the catalog actions it can perform (each routed to exactly one of its executors),
- the rules that recognise those actions in observed activity,
- factories for its executors and verifiers,
- a status check for the dashboard.

`app.integrations.INTEGRATIONS` lists them; the action catalog, the event classifier, the executor
and verifier registries and `/api/status` are all built from that list.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import urlparse

from app.models.canonical import RiskCategory, RiskLevel
from app.models.event import ActivityEvent
from app.models.strategy import ExecutionStrategyType


@dataclass(frozen=True)
class CatalogParameter:
    """An input consumed by a catalog action."""

    name: str
    description: str
    required: bool = True
    # Template resolved by the ExecutionEngine from upstream step outputs when the
    # parameter varies between observed sessions and no runtime value is supplied.
    upstream_template: Optional[str] = None


@dataclass(frozen=True)
class CatalogAction:
    """A single executable action with exact executor routing."""

    action_id: str
    application: str
    action: str
    description: str
    executor_name: str
    strategy: ExecutionStrategyType
    risk_level: RiskLevel
    risk_category: RiskCategory
    risk_reason: str
    requires_confirmation: bool = False
    parameters: Tuple[CatalogParameter, ...] = field(default_factory=tuple)
    produces: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def step_key(self) -> str:
        """DNA step key for this action (e.g. 'gmail:search_email')."""
        return f"{self.application.lower()}:{self.action}"

    def parameter(self, name: str) -> Optional[CatalogParameter]:
        return next((p for p in self.parameters if p.name == name), None)


@dataclass(frozen=True)
class ClassifiedAction:
    action: CatalogAction
    parameters: Dict[str, str]


# Recognise one observed event as one of this integration's actions, or return None.
Classifier = Callable[[ActivityEvent], Optional[ClassifiedAction]]
# (connected, human-readable detail). Never includes credentials.
StatusCheck = Callable[[], Tuple[bool, str]]


@dataclass(frozen=True)
class Integration:
    key: str  # catalog action ids are '<key>.<action>' and /api/status reports under this key
    name: str
    role: str  # one line for the dashboard: what WorkFlowOS uses it for
    actions: Tuple[CatalogAction, ...]
    classifiers: Tuple[Classifier, ...] = ()
    # Factories (not instances) so importing an integration never creates clients or touches the network.
    executors: Tuple[Callable[[], object], ...] = ()
    verifiers: Tuple[Callable[[], object], ...] = ()
    status: Optional[StatusCheck] = None

    def action(self, short_name: str) -> CatalogAction:
        """This integration's action by its short name, e.g. gmail.action('search_email')."""
        return next(a for a in self.actions if a.action == short_name)


# --------------------------------------------------------------------- URL helpers


def host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def host_matches(url: str, hosts: Tuple[str, ...]) -> bool:
    """True for the host itself or any subdomain (never a look-alike like mail.google.com.evil.example)."""
    h = host(url)
    return any(h == x or h.endswith("." + x) for x in hosts)
