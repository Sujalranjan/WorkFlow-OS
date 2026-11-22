"""The action catalog, for the workflow editor: every action WorkFlowOS can run, grouped by tool."""

from typing import Any, Dict, List

from fastapi import APIRouter

from app.integrations import INTEGRATIONS

router = APIRouter(prefix="/api/catalog", tags=["Action catalog"])


@router.get("")
def list_catalog() -> List[Dict[str, Any]]:
    return [
        {
            "key": integration.key,
            "name": integration.name,
            "actions": [
                {
                    "action_id": a.action_id,
                    "application": a.application,
                    "action": a.action,
                    "description": a.description,
                    "risk_level": a.risk_level.value,
                    "risk_reason": a.risk_reason,
                    "requires_confirmation": a.requires_confirmation,
                    "parameters": [
                        {
                            "name": p.name,
                            "description": p.description,
                            "required": p.required,
                            "default_upstream": p.upstream_template[1:-1] if p.upstream_template else None,
                        }
                        for p in a.parameters
                    ],
                    "produces": list(a.produces),
                    "requires": list(a.requires),
                }
                for a in integration.actions
            ],
        }
        for integration in INTEGRATIONS
    ]
