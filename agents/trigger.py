"""
Fabric → Foundry Trigger

Called from notebook 03_gold_fraud_score.ipynb after Gold table is written.
Queries all open HIGH risk claims above the threshold and dispatches the
Foundry multi-agent investigation for each one.

Inside Fabric: runs as Managed Identity (no credentials needed).
Locally: uses DefaultAzureCredential (az login).

Usage:
    # From Fabric notebook (last cell of 03_gold_fraud_score.ipynb):
    from agents.trigger import run_pending_investigations
    run_pending_investigations(spark)

    # CLI testing:
    python agents/trigger.py --claim-id CLM-2024-7734 --dry-run
    python agents/trigger.py --all                   # process all pending
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# When executed as `python agents/trigger.py`, Python only adds `agents/` to
# sys.path. Insert the repo root so `from agents.*` imports resolve correctly.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _parse_float_setting(settings: dict[str, str], key: str, default: str) -> float:
    """Parse numeric settings safely, tolerating inline comments in .env values."""
    raw = settings.get(key, default)
    # Accept values like "50000    # comment" by removing trailing inline comments.
    cleaned = raw.split("#", 1)[0].strip()
    if not cleaned:
        cleaned = default
    return float(cleaned)


def _load_settings() -> dict[str, str]:
    env_path = Path(__file__).parent.parent / "config" / "settings.env"
    settings: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                settings[k.strip()] = v.strip()
    return {**settings, **os.environ}   # env vars override file


def _get_high_risk_claims(spark, min_score: float, min_amount: float) -> list[dict]:
    """Query Gold table for uninvestigated HIGH risk open claims."""
    rows = spark.sql(f"""
        SELECT
            claim_id, claimant_id, property_id, state, claim_type,
            claim_amount, fraud_risk_score, risk_tier, primary_alert,
            id_verified, value_pct_change, claim_velocity_24mo,
            has_lien, account_age_days, assigned_investigator
        FROM gold_claims_fraud_scored
        WHERE risk_tier = 'HIGH'
          AND claim_status IN ('OPEN', 'UNDER_REVIEW')
          AND fraud_risk_score >= {min_score}
          AND claim_amount >= {min_amount}
        ORDER BY fraud_risk_score DESC
    """).collect()
    return [row.asDict() for row in rows]


def _write_report_to_lakehouse(spark, report, lakehouse_name: str):
    """Write investigation report to Lakehouse audit table."""
    import pandas as pd
    audit_row = report.to_audit_row()
    audit_df = spark.createDataFrame(pd.DataFrame([audit_row]))

    (
        audit_df
        .write.format("delta")
        .mode("append")
        .option("mergeSchema", "true")
        .saveAsTable("gold_investigation_audit_log")
    )

    # Also write full JSON report to Files section
    report_path = f"/lakehouse/default/Files/investigation_reports/{report.claim_id}.json"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report.model_dump(mode="json"), f, indent=2, default=str)

    logger.info("Report written: %s", report_path)


def run_pending_investigations(spark=None, dry_run: bool = False):
    """
    Main entry point — call this from notebook 03 or CLI.

    Args:
        spark:   Active SparkSession (required when called from notebook)
        dry_run: If True, fetch claims but skip Foundry calls (for testing)
    """
    settings = _load_settings()
    min_score = _parse_float_setting(settings, "FRAUD_HIGH_THRESHOLD", "0.75")
    min_amount = _parse_float_setting(settings, "FRAUD_ALERT_AMOUNT_MIN", "50000")

    # Import here so Fabric can call this without the full agent stack if dry_run
    from agents.models import ClaimInput, RiskTier

    # Get claims to investigate
    if spark is not None:
        claims_data = _get_high_risk_claims(spark, min_score, min_amount)
    else:
        # Local test: use a synthetic claim
        claims_data = [{
            "claim_id": "CLM-2024-7734",
            "claimant_id": "CLM-ID-10042",
            "property_id": "PROP-20187",
            "state": "TX",
            "claim_type": "WIRE_FRAUD",
            "claim_amount": 182400.0,
            "fraud_risk_score": 0.94,
            "risk_tier": "HIGH",
            "primary_alert": "IDENTITY_VERIFICATION_REQUIRED",
            "id_verified": False,
            "value_pct_change": 31.4,
            "claim_velocity_24mo": 3,
            "has_lien": True,
            "account_age_days": 145,
            "assigned_investigator": "J.Rivera",
        }]

    logger.info("Found %d claims to investigate (score≥%.2f, amount≥$%.0f)",
                len(claims_data), min_score, min_amount)

    if not claims_data:
        logger.info("No pending high-risk claims. Nothing to do.")
        return

    if dry_run:
        logger.info("[DRY RUN] Would investigate: %s",
                    [c["claim_id"] for c in claims_data])
        return

    from agents.orchestrator import investigate

    for claim_data in claims_data:
        try:
            claim = ClaimInput(
                **{k: v for k, v in claim_data.items()
                   if k in ClaimInput.model_fields}
            )
            report = investigate(claim)

            # Print summary
            print(f"\n{'='*60}")
            print(f"INVESTIGATION COMPLETE: {claim.claim_id}")
            print(f"  Composite Probability: {report.composite_fraud_probability:.3f}")
            print(f"  Recommended Action:    {report.recommended_action.value}")
            print(f"  SAR Required:          {report.compliance_result.sar_required}")
            print(f"  Action Rationale:      {report.action_rationale}")
            print(f"  Total Latency:         {report.total_latency_ms}ms")

            # Agent statuses
            for agent_result in [
                report.identity_result,
                report.property_result,
                report.claims_pattern_result,
                report.compliance_result,
            ]:
                print(f"  [{agent_result.agent_name}] → {agent_result.status.value}")
                for finding in agent_result.findings[:2]:   # top 2 findings each
                    print(f"    • {finding}")

            if spark is not None:
                _write_report_to_lakehouse(
                    spark, report, settings.get("FABRIC_LAKEHOUSE_NAME", "stewart_title_claims")
                )

        except Exception as exc:
            logger.exception("Investigation failed for %s: %s",
                             claim_data.get("claim_id", "?"), exc)


# ── CLI Entry Point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trigger Foundry fraud investigations")
    parser.add_argument("--claim-id",  help="Investigate a specific claim ID")
    parser.add_argument("--all",       action="store_true",
                        help="Investigate all pending HIGH risk claims")
    parser.add_argument("--dry-run",   action="store_true",
                        help="Fetch claims but skip Foundry calls")
    args = parser.parse_args()

    if args.claim_id:
        # Single-claim mode — override claims_data with just this claim
        os.environ["_TRIGGER_CLAIM_ID"] = args.claim_id

    run_pending_investigations(spark=None, dry_run=args.dry_run)
