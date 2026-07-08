"""
register_data_agent.py

Creates and configures the Fabric Data Agent via REST API:
- Creates the Data Agent item in the workspace
- Attaches the Gold lakehouse table as the data source
- Injects the system prompt from config/data_agent_config.json

NOTE: Data Agent creation via API is in preview. If the API call fails,
follow the manual steps in DEPLOYMENT.md Phase 4 — the agent configuration
JSON in config/data_agent_config.json is ready to paste directly.

Usage:
    python scripts/register_data_agent.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.foundry_client import _load_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

FABRIC_API_BASE = "https://api.fabric.microsoft.com/v1"
CONFIG_DIR      = Path(__file__).parent.parent / "config"


def _get_token() -> str:
    from azure.identity import DefaultAzureCredential
    return DefaultAzureCredential().get_token(
        "https://api.fabric.microsoft.com/.default"
    ).token


def _fabric_request(method: str, path: str, body: dict | None, token: str) -> dict:
    import urllib.request
    url  = f"{FABRIC_API_BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()}") from e


def register_data_agent():
    env          = _load_env()
    workspace_id  = env.get("FABRIC_WORKSPACE_ID", "").strip()
    lakehouse_id  = env.get("FABRIC_LAKEHOUSE_ID",  "").strip()
    agent_config  = json.loads((CONFIG_DIR / "data_agent_config.json").read_text())

    if not workspace_id or workspace_id.startswith("xxx"):
        print("❌ FABRIC_WORKSPACE_ID not set in config/settings.env")
        sys.exit(1)

    token = _get_token()

    # Check if agent already exists
    items    = _fabric_request("GET", f"/workspaces/{workspace_id}/items", None, token)
    existing = next(
        (i for i in items.get("value", [])
         if i.get("type") == "DataAgent" and i.get("displayName") == agent_config["agent_name"]),
        None,
    )

    agent_definition = {
        "systemPrompt": agent_config["system_prompt"],
        "dataSources": [
            {
                "type":         "Lakehouse",
                "workspaceId":  workspace_id,
                "itemId":       lakehouse_id,
                "tables":       [agent_config["target_table"]] + agent_config.get("secondary_tables", []),
            }
        ],
        "exampleQueries": [
            {"naturalLanguage": q["natural_language"], "sql": q["sql"]}
            for q in agent_config.get("example_queries", [])
        ],
    }

    try:
        if existing:
            agent_id = existing["id"]
            logger.info("Updating existing Data Agent: %s", agent_id)
            _fabric_request("PATCH", f"/workspaces/{workspace_id}/items/{agent_id}", {
                "definition": agent_definition
            }, token)
        else:
            logger.info("Creating Data Agent: %s", agent_config["agent_name"])
            result = _fabric_request("POST", f"/workspaces/{workspace_id}/items", {
                "displayName": agent_config["agent_name"],
                "type":        "DataAgent",
                "definition":  agent_definition,
            }, token)
            agent_id = result.get("id")

        print(f"\n✅ Data Agent configured: {agent_config['agent_name']}")
        print(f"   Agent ID: {agent_id}")
        print(f"\n   Add to config/settings.env:")
        print(f"   FABRIC_AGENT_ID={agent_id}")
        print(f"\n   Test it in Fabric UI: Workspace → {agent_config['agent_name']} → Chat")

    except Exception as exc:
        logger.error("Data Agent API call failed: %s", exc)
        print("\n⚠️  Automatic registration failed (Data Agent API may still be in preview).")
        print("   Use the MANUAL steps in DEPLOYMENT.md Phase 4 instead.")
        print(f"\n   Your system prompt is ready in: config/data_agent_config.json")
        print(f"   Paste the 'system_prompt' field into the agent Instructions tab.")


if __name__ == "__main__":
    register_data_agent()
