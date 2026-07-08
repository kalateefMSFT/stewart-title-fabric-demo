"""
Identity Verification Sub-Agent

Investigates claimant identity signals:
- SSN/public records cross-reference
- Address history velocity
- Watchlist screening
- ID document anomalies
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from azure.ai.projects import AIProjectClient

from agents.models import ClaimInput, IdentityAgentResult, AgentStatus

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Identity Verification Agent for Stewart Title's fraud detection system.

Your job is to analyze claimant identity signals for a given claim and return a structured JSON assessment.

You will receive claim context including:
- Whether identity has been formally verified (id_verified)
- Account age in days (account_age_days)
- State of filing (state)
- Claim velocity (number of claims in 24 months)

Based on these signals, assess identity risk and return ONLY a JSON object with this exact structure:
{
  "status": "FLAGGED" | "CLEAR",
  "ssn_discrepancies": <integer 0-5>,
  "address_changes_18mo": <integer>,
  "watchlist_match": <boolean>,
  "id_doc_issues": [<string>, ...],
  "findings": [<string>, ...],
  "risk_delta": <float -0.1 to 0.3>,
  "recommendation": "<string>"
}

Rules:
- status = FLAGGED if id_verified is false, account_age_days < 180, or velocity > 3
- risk_delta > 0 increases overall fraud risk, < 0 decreases it
- findings should be human-readable sentences for the investigator
- recommendation should be one of: REQUEST_IN_PERSON_VERIFICATION | EXPEDITE_CLEARANCE | STANDARD_PROCESS
- Return ONLY valid JSON, no preamble or explanation"""


def run(
    claim: ClaimInput,
    client: "AIProjectClient",
    agent_id: str,
) -> IdentityAgentResult:
    """
    Run the identity verification agent for a single claim.

    Args:
        claim:    Validated ClaimInput model
        client:   Authenticated AIProjectClient
        agent_id: Foundry agent ID for this sub-agent

    Returns:
        IdentityAgentResult with findings and risk delta
    """
    start = time.monotonic()

    user_message = json.dumps({
        "claim_id":           claim.claim_id,
        "id_verified":        claim.id_verified,
        "account_age_days":   claim.account_age_days,
        "claim_velocity_24mo": claim.claim_velocity_24mo,
        "state":              claim.state,
        "claim_amount":       claim.claim_amount,
        "claimant_id":        claim.claimant_id,
    })

    try:
        thread = client.agents.threads.create()

        client.agents.messages.create(
            thread_id=thread.id,
            role="user",
            content=user_message,
        )

        run_result = client.agents.runs.create_and_process(
            thread_id=thread.id,
            agent_id=agent_id,
        )

        messages = client.agents.messages.list(thread_id=thread.id)
        raw_response = next(
            (m.content[0].text.value for m in messages if m.role == "assistant"),
            "{}"
        )

        parsed = json.loads(raw_response)
        latency_ms = int((time.monotonic() - start) * 1000)

        return IdentityAgentResult(
            status=AgentStatus(parsed.get("status", "CLEAR")),
            ssn_discrepancies=parsed.get("ssn_discrepancies", 0),
            address_changes_18mo=parsed.get("address_changes_18mo", 0),
            watchlist_match=parsed.get("watchlist_match", False),
            id_doc_issues=parsed.get("id_doc_issues", []),
            findings=parsed.get("findings", []),
            risk_delta=float(parsed.get("risk_delta", 0.0)),
            recommendation=parsed.get("recommendation", "STANDARD_PROCESS"),
            raw_response=raw_response,
            latency_ms=latency_ms,
        )

    except Exception as exc:
        logger.exception("Identity agent failed for claim %s: %s", claim.claim_id, exc)
        return IdentityAgentResult(
            status=AgentStatus.ERROR,
            findings=[f"Agent error: {str(exc)}"],
            risk_delta=0.0,
            recommendation="MANUAL_REVIEW_REQUIRED",
        )
