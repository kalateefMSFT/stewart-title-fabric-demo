"""
Orchestrator Agent

Dispatches all four sub-agents in parallel for a given claim, then synthesizes
their findings into a consolidated InvestigationReport using the Foundry
orchestrator agent for the final narrative synthesis step.

All four sub-agents run concurrently via ThreadPoolExecutor — typical wall-clock
time is ~10-15 seconds for a full investigation, vs. 2-4 minutes sequential.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from agents.foundry_client import get_foundry_client, get_agent_ids
from agents.models import (
    ClaimInput, InvestigationReport, OrchestratorDecision, RiskTier,
    IdentityAgentResult, PropertyAgentResult,
    ClaimsPatternAgentResult, ComplianceAgentResult,
    AgentStatus,
)
from agents.sub_agents import (
    identity_agent,
    property_agent,
    claims_pattern_agent,
    compliance_agent,
)

logger = logging.getLogger(__name__)


ORCHESTRATOR_SYNTHESIS_PROMPT = """You are the Orchestrator for Stewart Title's multi-agent fraud investigation system.

You will receive structured JSON output from 4 specialist agents that have each independently
analyzed a suspicious insurance claim. Your job is to synthesize their findings into a
final investigation decision.

Return ONLY a JSON object:
{
  "composite_fraud_probability": <float 0.0-0.99>,
  "recommended_action": "PLACE_PAYOUT_HOLD" | "ESCALATE_TO_SIU" | "REQUEST_DOCUMENTATION" | "STANDARD_REVIEW" | "CLEAR_FOR_PAYMENT",
  "action_rationale": "<2-3 sentence explanation for the investigator>"
}

Guidelines:
- composite_fraud_probability should weight all 4 agent risk_deltas against the original score
- PLACE_PAYOUT_HOLD + ESCALATE_TO_SIU when 3+ agents flag issues
- REQUEST_DOCUMENTATION when 1-2 agents flag, no confirmed fraud pattern
- CLEAR_FOR_PAYMENT only when all 4 agents return CLEAR status
- action_rationale must reference specific findings, not just say 'high risk'
- Return ONLY valid JSON, no preamble"""


def _run_sub_agent(agent_name: str, fn, claim: ClaimInput, client, agent_id: str):
    """Wrapper for executor — returns (agent_name, result)."""
    logger.info("Starting sub-agent: %s for claim %s", agent_name, claim.claim_id)
    result = fn(claim, client, agent_id)
    logger.info("Completed sub-agent: %s — status: %s", agent_name, result.status)
    return agent_name, result


def investigate(
    claim: ClaimInput,
    foundry_endpoint: Optional[str] = None,
) -> InvestigationReport:
    """
    Run the full multi-agent investigation for a single claim.

    Args:
        claim:            Validated ClaimInput model
        foundry_endpoint: Optional override; falls back to env/settings.env

    Returns:
        InvestigationReport with all findings and recommended action
    """
    wall_start = time.monotonic()
    logger.info("=== Starting investigation for %s (score=%.3f) ===",
                claim.claim_id, claim.fraud_risk_score)

    client   = get_foundry_client(foundry_endpoint)
    agent_ids = get_agent_ids()

    # ── Dispatch all sub-agents in parallel ──────────────────────────────────
    sub_agent_tasks = [
        ("identity",       identity_agent.run,       agent_ids["identity"]),
        ("property",       property_agent.run,       agent_ids["property"]),
        ("claims_pattern", claims_pattern_agent.run, agent_ids["claims_pattern"]),
        ("compliance",     compliance_agent.run,     agent_ids["compliance"]),
    ]

    results: dict = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_run_sub_agent, name, fn, claim, client, aid): name
            for name, fn, aid in sub_agent_tasks
        }
        for future in as_completed(futures):
            name, result = future.result()
            results[name] = result

    identity_result:  IdentityAgentResult       = results["identity"]
    property_result:  PropertyAgentResult        = results["property"]
    pattern_result:   ClaimsPatternAgentResult   = results["claims_pattern"]
    compliance_result: ComplianceAgentResult     = results["compliance"]

    # ── Orchestrator synthesis via Foundry ───────────────────────────────────
    synthesis_input = json.dumps({
        "claim_id":           claim.claim_id,
        "claim_amount":       claim.claim_amount,
        "original_score":     claim.fraud_risk_score,
        "risk_tier":          claim.risk_tier.value,
        "identity": {
            "status":     identity_result.status.value,
            "risk_delta": identity_result.risk_delta,
            "findings":   identity_result.findings,
        },
        "property": {
            "status":     property_result.status.value,
            "risk_delta": property_result.risk_delta,
            "findings":   property_result.findings,
        },
        "claims_pattern": {
            "status":     pattern_result.status.value,
            "risk_delta": pattern_result.risk_delta,
            "findings":   pattern_result.findings,
        },
        "compliance": {
            "status":     compliance_result.status.value,
            "sar_required": compliance_result.sar_required,
            "findings":   compliance_result.findings,
        },
    })

    try:
        thread = client.agents.threads.create()
        client.agents.messages.create(
            thread_id=thread.id, role="user", content=synthesis_input
        )
        client.agents.runs.create_and_process(
            thread_id=thread.id,
            agent_id=agent_ids["orchestrator"],
        )
        messages = client.agents.messages.list(thread_id=thread.id)
        synthesis_raw = next(
            (m.content[0].text.value for m in messages if m.role == "assistant"), "{}"
        )
        synthesis = json.loads(synthesis_raw)
    except Exception as exc:
        logger.exception("Orchestrator synthesis failed: %s", exc)
        # Fallback: rule-based decision
        flagged_count = sum(
            1 for r in [identity_result, property_result, pattern_result, compliance_result]
            if r.status not in (AgentStatus.CLEAR, AgentStatus.ERROR)
        )
        synthesis = {
            "composite_fraud_probability": min(
                0.99,
                claim.fraud_risk_score + sum(
                    r.risk_delta for r in [identity_result, property_result,
                                           pattern_result, compliance_result]
                )
            ),
            "recommended_action": (
                "PLACE_PAYOUT_HOLD" if flagged_count >= 3
                else "ESCALATE_TO_SIU" if flagged_count == 2
                else "REQUEST_DOCUMENTATION" if flagged_count == 1
                else "STANDARD_REVIEW"
            ),
            "action_rationale": (
                f"Fallback decision: {flagged_count}/4 agents flagged this claim. "
                "Orchestrator synthesis failed — manual review required."
            ),
        }

    total_latency_ms = int((time.monotonic() - wall_start) * 1000)
    logger.info(
        "=== Investigation complete: %s → %s (%.0fms) ===",
        claim.claim_id,
        synthesis.get("recommended_action"),
        total_latency_ms,
    )

    return InvestigationReport(
        claim_id=claim.claim_id,
        claim_amount=claim.claim_amount,
        original_fraud_score=claim.fraud_risk_score,
        risk_tier=claim.risk_tier,
        identity_result=identity_result,
        property_result=property_result,
        claims_pattern_result=pattern_result,
        compliance_result=compliance_result,
        composite_fraud_probability=float(synthesis.get("composite_fraud_probability", claim.fraud_risk_score)),
        recommended_action=OrchestratorDecision(
            synthesis.get("recommended_action", "STANDARD_REVIEW")
        ),
        action_rationale=synthesis.get("action_rationale", ""),
        human_review_required=True,
        orchestrator_agent_id=agent_ids["orchestrator"],
        total_latency_ms=total_latency_ms,
    )
