"""
Pydantic models for the Stewart Title multi-agent investigation system.
Used for input validation, structured output, and audit logging.
"""

from __future__ import annotations
from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional
from datetime import datetime
from enum import Enum


# ── Enums ─────────────────────────────────────────────────────────────────────

class RiskTier(str, Enum):
    HIGH   = "HIGH"
    MEDIUM = "MEDIUM"
    LOW    = "LOW"

class AgentStatus(str, Enum):
    FLAGGED           = "FLAGGED"
    ANOMALY_DETECTED  = "ANOMALY_DETECTED"
    MATCH_FOUND       = "MATCH_FOUND"
    ACTION_REQUIRED   = "ACTION_REQUIRED"
    CLEAR             = "CLEAR"
    ERROR             = "ERROR"

class OrchestratorDecision(str, Enum):
    PLACE_PAYOUT_HOLD       = "PLACE_PAYOUT_HOLD"
    ESCALATE_TO_SIU         = "ESCALATE_TO_SIU"
    REQUEST_DOCUMENTATION   = "REQUEST_DOCUMENTATION"
    STANDARD_REVIEW         = "STANDARD_REVIEW"
    CLEAR_FOR_PAYMENT       = "CLEAR_FOR_PAYMENT"


# ── Input Models ──────────────────────────────────────────────────────────────

class ClaimInput(BaseModel):
    """Input to the orchestrator — one claim to investigate."""
    claim_id:           str   = Field(..., pattern=r"^CLM-\d{4}-\d+$")
    claimant_id:        str
    property_id:        str
    claim_amount:       float = Field(..., gt=0)
    fraud_risk_score:   float = Field(..., ge=0.0, le=1.0)
    risk_tier:          RiskTier
    primary_alert:      str
    state:              str   = Field(..., min_length=2, max_length=2)
    claim_type:         str
    id_verified:        bool
    value_pct_change:   float
    claim_velocity_24mo: int  = Field(..., ge=0)
    has_lien:           bool
    account_age_days:   int   = Field(..., ge=0)
    assigned_investigator: str

    @field_validator("state")
    @classmethod
    def state_uppercase(cls, v: str) -> str:
        return v.upper()


# ── Sub-Agent Output Models ───────────────────────────────────────────────────

class SubAgentResult(BaseModel):
    """Base output from any sub-agent."""
    agent_name:   str
    status:       AgentStatus
    findings:     list[str]   = Field(default_factory=list)
    risk_delta:   float       = Field(default=0.0, ge=-1.0, le=1.0,
                                      description="How much this agent adjusts composite risk")
    recommendation: str       = ""
    raw_response: Optional[str] = None
    latency_ms:   Optional[int] = None


class IdentityAgentResult(SubAgentResult):
    agent_name:               str = "IdentityVerificationAgent"
    ssn_discrepancies:        int = 0
    address_changes_18mo:     int = 0
    watchlist_match:          bool = False
    id_doc_issues:            list[str] = Field(default_factory=list)


class PropertyAgentResult(SubAgentResult):
    agent_name:               str = "PropertyHistoryAgent"
    value_change_pct:         float = 0.0
    title_transfers_24mo:     int = 0
    comparable_sale_gap_pct:  float = 0.0
    lien_count:               int = 0


class ClaimsPatternAgentResult(SubAgentResult):
    agent_name:               str = "ClaimsPatternAgent"
    pattern_cohort:           Optional[str] = None
    cohort_similarity_pct:    float = 0.0
    shared_identifiers:       list[str] = Field(default_factory=list)
    prior_denied_claims:      int = 0


class ComplianceAgentResult(SubAgentResult):
    agent_name:               str = "RegulatoryComplianceAgent"
    sar_required:             bool = False
    alta_practices_triggered: list[str] = Field(default_factory=list)
    state_disclosure_days:    Optional[int] = None
    regulatory_notes:         list[str] = Field(default_factory=list)


# ── Orchestrator Output ───────────────────────────────────────────────────────

class InvestigationReport(BaseModel):
    """Full structured output from the orchestrator — written to OneLake."""
    # Claim context
    claim_id:               str
    claim_amount:           float
    original_fraud_score:   float
    risk_tier:              RiskTier

    # Agent results
    identity_result:        IdentityAgentResult
    property_result:        PropertyAgentResult
    claims_pattern_result:  ClaimsPatternAgentResult
    compliance_result:      ComplianceAgentResult

    # Orchestrator synthesis
    composite_fraud_probability: float = Field(..., ge=0.0, le=1.0)
    recommended_action:     OrchestratorDecision
    action_rationale:       str
    human_review_required:  bool = True   # Always True for HIGH risk claims

    # Metadata
    investigated_at:        datetime = Field(default_factory=datetime.utcnow)
    model_version:          str = "gpt-4o-fraud"
    orchestrator_agent_id:  Optional[str] = None
    total_latency_ms:       Optional[int] = None

    def to_audit_row(self) -> dict:
        """Flattened dict for writing to Lakehouse audit table."""
        return {
            "claim_id":                     self.claim_id,
            "claim_amount":                 self.claim_amount,
            "original_fraud_score":         self.original_fraud_score,
            "composite_fraud_probability":  self.composite_fraud_probability,
            "recommended_action":           self.recommended_action.value,
            "human_review_required":        self.human_review_required,
            "identity_status":              self.identity_result.status.value,
            "property_status":              self.property_result.status.value,
            "pattern_status":               self.claims_pattern_result.status.value,
            "compliance_status":            self.compliance_result.status.value,
            "sar_required":                 self.compliance_result.sar_required,
            "investigated_at":              self.investigated_at.isoformat(),
            "model_version":                self.model_version,
        }
