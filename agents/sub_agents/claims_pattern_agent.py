"""
Claims Pattern Sub-Agent

Matches this claim against known fraud cohorts and historical patterns:
- Wire fraud pattern similarity scoring
- Shared identifiers (IP, address, bank account proxies)
- Prior denied / confirmed fraud linkage
- Velocity pattern classification
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from azure.ai.projects import AIProjectClient

from agents.models import ClaimInput, ClaimsPatternAgentResult, AgentStatus

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Claims Pattern Agent for Stewart Title's fraud detection system.

Your job is to analyze whether a claim matches known fraud patterns based on behavioral signals.

You will receive:
- claim_velocity_24mo: number of claims by this claimant in last 24 months
- fraud_risk_score: pre-computed ML score (0-1)
- primary_alert: highest-priority alert signal
- claim_type: type of claim
- claim_amount: dollar amount

Assess pattern-based fraud risk and return ONLY a JSON object:
{
  "status": "MATCH_FOUND" | "CLEAR",
  "pattern_cohort": "<string or null> e.g. WIRE_FRAUD_RING | VELOCITY_ABUSER | STRAW_BUYER_NETWORK",
  "cohort_similarity_pct": <float 0-100>,
  "shared_identifiers": [<string>, ...],
  "prior_denied_claims": <integer>,
  "findings": [<string>, ...],
  "risk_delta": <float -0.1 to 0.3>,
  "recommendation": "<string>"
}

Rules:
- status = MATCH_FOUND if velocity > 2 or fraud_risk_score > 0.75
- cohort_similarity_pct > 70 is a strong pattern match
- shared_identifiers are inferred from velocity and claim_type clustering
- recommendation: ESCALATE_TO_SIU | FLAG_FOR_NETWORK_ANALYSIS | STANDARD_PROCESS
- Return ONLY valid JSON"""


def run(
    claim: ClaimInput,
    client: "AIProjectClient",
    agent_id: str,
) -> ClaimsPatternAgentResult:
    start = time.monotonic()

    user_message = json.dumps({
        "claim_id":            claim.claim_id,
        "claimant_id":         claim.claimant_id,
        "claim_velocity_24mo": claim.claim_velocity_24mo,
        "fraud_risk_score":    claim.fraud_risk_score,
        "primary_alert":       claim.primary_alert,
        "claim_type":          claim.claim_type,
        "claim_amount":        claim.claim_amount,
        "state":               claim.state,
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

        return ClaimsPatternAgentResult(
            status=AgentStatus(parsed.get("status", "CLEAR")),
            pattern_cohort=parsed.get("pattern_cohort"),
            cohort_similarity_pct=float(parsed.get("cohort_similarity_pct", 0.0)),
            shared_identifiers=parsed.get("shared_identifiers", []),
            prior_denied_claims=parsed.get("prior_denied_claims", 0),
            findings=parsed.get("findings", []),
            risk_delta=float(parsed.get("risk_delta", 0.0)),
            recommendation=parsed.get("recommendation", "STANDARD_PROCESS"),
            raw_response=raw_response,
            latency_ms=latency_ms,
        )

    except Exception as exc:
        logger.exception("Pattern agent failed for claim %s: %s", claim.claim_id, exc)
        return ClaimsPatternAgentResult(
            status=AgentStatus.ERROR,
            findings=[f"Agent error: {str(exc)}"],
            risk_delta=0.0,
            recommendation="MANUAL_REVIEW_REQUIRED",
        )
