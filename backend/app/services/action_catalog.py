"""Action Catalog: the fixed vocabulary that bridges observation and execution.

Observed desktop/browser activity is only executable if it can be named exactly. The catalog lists
every action WorkFlowOS can actually perform, together with:

- the executor that performs it (routing is by exact name, never by keyword guessing),
- its deterministic risk classification,
- the parameters it consumes and where each parameter comes from at runtime.

The actions and the rules that recognise them in observed activity are declared per integration in
`app/integrations/` (one module per tool); this module assembles them.

`classify_event()` maps a single observed ActivityEvent to a catalog action using deterministic
rules (explicit `workflow_action` metadata, then each integration's URL/download/form rules). Events
that do not match remain ordinary observational context (e.g. window focus) and are never executed.

STRICT GUARANTEES:
- No LLM involvement: classification is pure pattern matching on event metadata.
- No message bodies, form contents (other than the CRM status field) or keystrokes are read.
"""

from typing import Dict, List, Optional

from app.integrations import INTEGRATIONS, all_actions
from app.integrations.base import CatalogAction, CatalogParameter, ClassifiedAction  # noqa: F401 - public API
from app.models.event import ActivityEvent

ACTION_CATALOG: Dict[str, CatalogAction] = all_actions()

_BY_STEP_KEY: Dict[str, CatalogAction] = {a.step_key: a for a in ACTION_CATALOG.values()}


def get_action(action_id: Optional[str]) -> Optional[CatalogAction]:
    return ACTION_CATALOG.get(action_id) if action_id else None


def get_action_by_step_key(step_key: Optional[str]) -> Optional[CatalogAction]:
    return _BY_STEP_KEY.get(step_key) if step_key else None


def list_actions() -> List[CatalogAction]:
    return list(ACTION_CATALOG.values())


def classify_event(evt: ActivityEvent) -> Optional[ClassifiedAction]:
    """Deterministically map an observed event to a catalog action, or None."""
    md = evt.metadata or {}

    explicit = md.get("workflow_action")
    if isinstance(explicit, str) and explicit in ACTION_CATALOG:
        params = md.get("action_parameters") or {}
        clean = {str(k): str(v) for k, v in params.items() if v is not None} if isinstance(params, dict) else {}
        return ClassifiedAction(ACTION_CATALOG[explicit], clean)

    for integration in INTEGRATIONS:
        for classifier in integration.classifiers:
            found = classifier(evt)
            if found is not None:
                return found
    return None


def step_key_for_event(evt: ActivityEvent) -> str:
    """The normalized step key used by discovery and DNA extraction."""
    classified = classify_event(evt)
    if classified:
        return classified.action.step_key
    app = (evt.application or "").strip().lower() or "unknown_app"
    return f"{app}:{evt.event_type.value}"


def application_for_event(evt: ActivityEvent) -> str:
    classified = classify_event(evt)
    if classified:
        return classified.action.application
    return evt.application or "Unknown"
