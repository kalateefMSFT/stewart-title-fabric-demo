"""
Property History Sub-Agent

Investigates property-level fraud signals:
- Abnormal value appreciation relative to market
- Rapid title transfer history
- Active liens
- Comparable sales gap analysis
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from azure.ai.projects import AIProjectClient

from agents.models import ClaimInput, PropertyAgentResult, AgentStatus

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Property History Agent for Stewart Title's fraud detection system.

Your job is to analyze property-level risk signals for a title insurance claim and return a structured JSON assessment.

You will receive:
- value_pct_change: % change in property value since closing
- has_lien: whether the property has an active lien
- property_id: identifier for the property
- state: state of the property
- claim_type: type of claim filed

Assess property fraud risk and return ONLY a JSON object:
{
  "status": "ANOMALY_DETECTED" | "CLEAR",
  "value_change_pct": <float>,
  "title_transfers_24mo": <integer 0-5, estimated from value volatility>,
  "comparable_sale_gap_pct": <float, estimated gap from market>,
  "lien_count": <integer>,
  "findings": [<string>, ...],
  "risk_delta": <float -0.1 to 0.3>,
  "recommendation": "<string>"
}

Rules:
- status = ANOMALY_DETECTED if value_pct_change > 20% or has_lien is true
- title_transfers_24mo > 2 is a strong fraud signal in title insurance
- comparable_sale_gap_pct > 15 suggests inflated valuation
- recommendation: ORDER_INDEPENDENT_APPRAISAL | TITLE_SEARCH_REQUIRED | STANDARD_PROCESS
- Return ONLY valid JSON"""


def run(
    claim: ClaimInput,
    client: "AIProjectClient",
    agent_id: str,
) -> PropertyAgentResult:
    start = time.monotonic()

    user_message = json.dumps({
        "claim_id":          claim.claim_id,
        "property_id":       claim.property_id,
        "value_pct_change":  claim.value_pct_change,
        "has_lien":          claim.has_lien,
        "state":             claim.state,
        "claim_type":        claim.claim_type,
        "claim_amount":      claim.claim_amount,
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

        return PropertyAgentResult(
            status=AgentStatus(parsed.get("status", "CLEAR")),
            value_change_pct=float(parsed.get("value_change_pct", claim.value_pct_change)),
            title_transfers_24mo=parsed.get("title_transfers_24mo", 0),
            comparable_sale_gap_pct=float(parsed.get("comparable_sale_gap_pct", 0.0)),
            lien_count=parsed.get("lien_count", 1 if claim.has_lien else 0),
            findings=parsed.get("findings", []),
            risk_delta=float(parsed.get("risk_delta", 0.0)),
            recommendation=parsed.get("recommendation", "STANDARD_PROCESS"),
            raw_response=raw_response,
            latency_ms=latency_ms,
        )

    except Exception as exc:
        logger.exception("Property agent failed for claim %s: %s", claim.claim_id, exc)
        return PropertyAgentResult(
            status=AgentStatus.ERROR,
            findings=[f"Agent error: {str(exc)}"],
            risk_delta=0.0,
            recommendation="MANUAL_REVIEW_REQUIRED",
        )
