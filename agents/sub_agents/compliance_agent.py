"""
Regulatory Compliance Sub-Agent

Assesses mandatory regulatory obligations triggered by this claim:
- FinCEN SAR filing thresholds ($5K+, $10K+ suspicious activity)
- ALTA Best Practice obligations
- State-specific disclosure windows
- RESPA / CFPB requirements where applicable
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from azure.ai.projects import AIProjectClient

from agents.models import ClaimInput, ComplianceAgentResult, AgentStatus

logger = logging.getLogger(__name__)

# State-specific investigation disclosure windows (days)
STATE_DISCLOSURE_WINDOWS = {
    "TX": 10, "FL": 15, "CA": 20, "NY": 30, "IL": 15,
    "AZ": 10, "GA": 15, "NC": 15, "OH": 20, "PA": 20,
}

SYSTEM_PROMPT = """You are the Regulatory Compliance Agent for Stewart Title's fraud detection system.

Your job is to identify regulatory obligations triggered by a suspicious insurance claim.

You will receive claim details including amount, state, claim type, and fraud signals.

Key regulatory thresholds:
- FinCEN SAR: Required when suspicious activity involves $5,000+ and you know or suspect fraud
- ALTA Best Practice 7: Fraud prevention — triggered by any HIGH risk claim
- State disclosure: Variable window for notifying state insurance commissioner

Return ONLY a JSON object:
{
  "status": "ACTION_REQUIRED" | "CLEAR",
  "sar_required": <boolean>,
  "alta_practices_triggered": [<string>, ...],
  "state_disclosure_days": <integer or null>,
  "regulatory_notes": [<string>, ...],
  "findings": [<string>, ...],
  "risk_delta": 0.0,
  "recommendation": "<string>"
}

Rules:
- sar_required = true if claim_amount >= 5000 AND risk_tier = 'HIGH'
- Always include the relevant state disclosure window in regulatory_notes
- alta_practices_triggered: list applicable ALTA Best Practices by number and name
- recommendation: INITIATE_SAR_FILING | NOTIFY_STATE_COMMISSIONER | DOCUMENT_AND_MONITOR | STANDARD_PROCESS
- Return ONLY valid JSON"""


def run(
    claim: ClaimInput,
    client: "AIProjectClient",
    agent_id: str,
) -> ComplianceAgentResult:
    start = time.monotonic()

    disclosure_days = STATE_DISCLOSURE_WINDOWS.get(claim.state.upper())

    user_message = json.dumps({
        "claim_id":          claim.claim_id,
        "claim_amount":      claim.claim_amount,
        "claim_type":        claim.claim_type,
        "state":             claim.state,
        "risk_tier":         claim.risk_tier.value,
        "fraud_risk_score":  claim.fraud_risk_score,
        "primary_alert":     claim.primary_alert,
        "state_disclosure_days": disclosure_days,
    })

    try:
        thread = client.agents.threads.create()
        client.agents.messages.create(
            thread_id=thread.id, role="user", content=user_message
        )
        client.agents.runs.create_and_process(
            thread_id=thread.id, agent_id=agent_id
        )

        messages = client.agents.messages.list(thread_id=thread.id)
        raw_response = next(
            (m.content[0].text.value for m in messages if m.role == "assistant"), "{}"
        )

        parsed = json.loads(raw_response)
        latency_ms = int((time.monotonic() - start) * 1000)

        return ComplianceAgentResult(
            status=AgentStatus(parsed.get("status", "CLEAR")),
            sar_required=parsed.get("sar_required", False),
            alta_practices_triggered=parsed.get("alta_practices_triggered", []),
            state_disclosure_days=parsed.get("state_disclosure_days", disclosure_days),
            regulatory_notes=parsed.get("regulatory_notes", []),
            findings=parsed.get("findings", []),
            risk_delta=float(parsed.get("risk_delta", 0.0)),
            recommendation=parsed.get("recommendation", "STANDARD_PROCESS"),
            raw_response=raw_response,
            latency_ms=latency_ms,
        )

    except Exception as exc:
        logger.exception("Compliance agent failed for claim %s: %s", claim.claim_id, exc)
        return ComplianceAgentResult(
            status=AgentStatus.ERROR,
            findings=[f"Agent error: {str(exc)}"],
            risk_delta=0.0,
            recommendation="MANUAL_REVIEW_REQUIRED",
        )
