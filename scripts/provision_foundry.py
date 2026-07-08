"""
provision_foundry.py

Creates and registers all 5 agents (4 specialists + 1 orchestrator) in the
Azure AI Foundry project. Writes the resulting agent IDs to config/settings.env.

Run once per environment:
    python scripts/provision_foundry.py

Prerequisites:
    - az login (or AZURE_* env vars set)
    - FOUNDRY_PROJECT_ENDPOINT set in config/settings.env
    - pip install -r agents/requirements.txt
"""

from __future__ import annotations

import os
import sys
import json
import logging
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.foundry_client import get_foundry_client, _load_env
from agents.sub_agents.identity_agent      import SYSTEM_PROMPT as IDENTITY_PROMPT
from agents.sub_agents.property_agent      import SYSTEM_PROMPT as PROPERTY_PROMPT
from agents.sub_agents.claims_pattern_agent import SYSTEM_PROMPT as PATTERN_PROMPT
from agents.sub_agents.compliance_agent    import SYSTEM_PROMPT as COMPLIANCE_PROMPT
from agents.orchestrator                   import ORCHESTRATOR_SYNTHESIS_PROMPT
from azure.ai.projects.models import PromptAgentDefinition

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

AGENT_DEFINITIONS = [
    {
        "key":         "identity",
        "env_key":     "AGENT_ID_IDENTITY",
        "name":        "StewartTitle-IdentityVerificationAgent",
        "description": "Analyzes claimant identity signals: SSN, address history, watchlist, account age",
        "prompt":      IDENTITY_PROMPT,
    },
    {
        "key":         "property",
        "env_key":     "AGENT_ID_PROPERTY",
        "name":        "StewartTitle-PropertyHistoryAgent",
        "description": "Analyzes property-level fraud signals: value spikes, title transfers, liens",
        "prompt":      PROPERTY_PROMPT,
    },
    {
        "key":         "claims_pattern",
        "env_key":     "AGENT_ID_CLAIMS_PATTERN",
        "name":        "StewartTitle-ClaimsPatternAgent",
        "description": "Matches claims against known fraud cohorts and behavioral patterns",
        "prompt":      PATTERN_PROMPT,
    },
    {
        "key":         "compliance",
        "env_key":     "AGENT_ID_COMPLIANCE",
        "name":        "StewartTitle-RegulatoryComplianceAgent",
        "description": "Identifies FinCEN SAR, ALTA Best Practice, and state disclosure obligations",
        "prompt":      COMPLIANCE_PROMPT,
    },
    {
        "key":         "orchestrator",
        "env_key":     "AGENT_ID_ORCHESTRATOR",
        "name":        "StewartTitle-OrchestratorAgent",
        "description": "Synthesizes findings from all sub-agents into a final investigation decision",
        "prompt":      ORCHESTRATOR_SYNTHESIS_PROMPT,
    },
]


def _update_settings_env(new_values: dict[str, str], env_path: Path):
    """Write agent IDs back into config/settings.env."""
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    updated_keys = set()
    new_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _, _ = stripped.partition("=")
            key = key.strip()
            if key in new_values:
                new_lines.append(f"{key}={new_values[key]}")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    # Append any keys that weren't already in the file
    for key, val in new_values.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(new_lines) + "\n")
    logger.info("Updated %s with %d agent IDs", env_path, len(new_values))


def provision(model_deployment: str | None = None) -> dict[str, str]:
    """
    Create all agents in Foundry and return their IDs.

    Args:
        model_deployment: GPT-4o deployment name. Falls back to settings.env.

    Returns:
        Dict mapping agent key → agent ID string
    """
    env      = _load_env()
    client   = get_foundry_client()
    model    = (
        model_deployment
        or os.environ.get("FOUNDRY_MODEL_DEPLOYMENT")
        or env.get("FOUNDRY_MODEL_DEPLOYMENT", "gpt-4o-fraud")
    )

    logger.info("Provisioning %d agents on model: %s", len(AGENT_DEFINITIONS), model)

    agent_ids: dict[str, str] = {}
    env_updates: dict[str, str] = {}

    for defn in AGENT_DEFINITIONS:
        logger.info("Creating agent: %s", defn["name"])
        try:
            agent_definition = PromptAgentDefinition(
                kind="prompt",
                model=model,
                instructions=defn["prompt"],
            )
            agent = client.agents.create(
                name=defn["name"],
                definition=agent_definition,
                description=defn["description"],
            )
            agent_ids[defn["key"]] = agent.id
            env_updates[defn["env_key"]] = agent.id
            logger.info("  ✅ %s → %s", defn["name"], agent.id)
        except Exception as exc:
            logger.error("  ❌ Failed to create %s: %s", defn["name"], exc)
            raise

    # Persist IDs to settings.env
    env_path = Path(__file__).parent.parent / "config" / "settings.env"
    if env_path.exists():
        _update_settings_env(env_updates, env_path)
    else:
        logger.warning(
            "config/settings.env not found — copy settings.env.example and fill in values. "
            "Agent IDs printed below."
        )

    # Also write to agent_ids.json for reference
    ids_path = Path(__file__).parent.parent / "config" / "agent_ids.json"
    ids_path.write_text(json.dumps({**agent_ids, "model": model}, indent=2))
    logger.info("Agent IDs written to %s", ids_path)

    print("\n" + "=" * 55)
    print("FOUNDRY AGENTS PROVISIONED")
    print("=" * 55)
    for key, aid in agent_ids.items():
        print(f"  {key:<20} {aid}")
    print()
    print("IDs written to config/settings.env and config/agent_ids.json")
    print("=" * 55)

    return agent_ids


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Provision Stewart Title Foundry agents")
    parser.add_argument("--model", default=None, help="GPT-4o deployment name")
    args = parser.parse_args()
    provision(model_deployment=args.model)
