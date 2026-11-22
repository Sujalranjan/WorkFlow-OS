"""Every external tool WorkFlowOS can observe and act on, declared in one place.

Adding an integration: create a module like `gmail.py` (actions, classifiers, executor and verifier
factories, status check), add it to INTEGRATIONS, and add tests. The action catalog, the event
classifier, the executor/verifier registries and /api/status pick it up from here.
"""

from typing import Dict, List, Optional

from app.integrations.base import (  # noqa: F401 - re-exported
    CatalogAction,
    CatalogParameter,
    ClassifiedAction,
    Integration,
)
from app.integrations.demo_crm import DEMO_CRM
from app.integrations.gmail import GMAIL
from app.integrations.slack import SLACK

# Order matters only for tie-breaking: classifiers are tried in this order (they never overlap).
INTEGRATIONS: List[Integration] = [GMAIL, DEMO_CRM, SLACK]


def get_integration(key: str) -> Optional[Integration]:
    return next((i for i in INTEGRATIONS if i.key == key), None)


def all_actions() -> Dict[str, CatalogAction]:
    actions: Dict[str, CatalogAction] = {}
    for integration in INTEGRATIONS:
        for action in integration.actions:
            if action.action_id in actions:
                raise RuntimeError(f"Duplicate catalog action {action.action_id}")
            actions[action.action_id] = action
    return actions
