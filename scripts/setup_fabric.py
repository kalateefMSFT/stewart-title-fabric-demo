"""
setup_fabric.py

Verifies Fabric workspace connectivity and lakehouse existence via Fabric REST API.
Prints the IDs you need to paste into config/settings.env.

NOTE: Workspace and Fabric capacity must be created manually in the Fabric UI
(see DEPLOYMENT.md Phase 2). This script validates and retrieves IDs.

Usage:
    python scripts/setup_fabric.py
"""

from __future__ import annotations

import os
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.foundry_client import _load_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

FABRIC_API_BASE = "https://api.fabric.microsoft.com/v1"


def _get_token() -> str:
    """Get an access token for the Fabric REST API using Azure credential."""
    from azure.identity import DefaultAzureCredential
    credential = DefaultAzureCredential()
    token = credential.get_token("https://api.fabric.microsoft.com/.default")
    return token.token


def _fabric_get(path: str, token: str) -> dict:
    import urllib.request, json as json_lib
    url = f"{FABRIC_API_BASE}{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    })
    with urllib.request.urlopen(req) as resp:
        return json_lib.loads(resp.read())


def _fabric_post(path: str, body: dict, token: str) -> dict:
    import urllib.request, json as json_lib
    url  = f"{FABRIC_API_BASE}{path}"
    data = json_lib.dumps(body).encode()
    req  = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    })
    with urllib.request.urlopen(req) as resp:
        return json_lib.loads(resp.read())


def verify_and_show_ids():
    env = _load_env()

    workspace_id   = env.get("FABRIC_WORKSPACE_ID", "").strip()
    lakehouse_name = env.get("FABRIC_LAKEHOUSE_NAME", "stewart_title_claims").strip()

    if not workspace_id or workspace_id == "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx":
        print("⚠️  FABRIC_WORKSPACE_ID not set in config/settings.env")
        print("   Create the workspace manually in Fabric UI, then paste the ID.")
        print("   See DEPLOYMENT.md Phase 2.")
        return

    print("Connecting to Fabric REST API...")
    token = _get_token()

    # Verify workspace
    try:
        ws = _fabric_get(f"/workspaces/{workspace_id}", token)
        print(f"✅ Workspace found: '{ws.get('displayName')}' (ID: {workspace_id})")
    except Exception as exc:
        print(f"❌ Cannot reach workspace {workspace_id}: {exc}")
        print("   Check FABRIC_WORKSPACE_ID in config/settings.env")
        return

    # List lakehouses in workspace
    try:
        items = _fabric_get(f"/workspaces/{workspace_id}/items?type=Lakehouse", token)
        lakehouses = items.get("value", [])
        print(f"\n   Lakehouses in workspace:")
        for lh in lakehouses:
            marker = " ← target" if lh.get("displayName") == lakehouse_name else ""
            print(f"     {lh['displayName']} — {lh['id']}{marker}")

        target = next((lh for lh in lakehouses if lh.get("displayName") == lakehouse_name), None)
        if target:
            print(f"\n✅ Lakehouse '{lakehouse_name}' found")
            print(f"   FABRIC_LAKEHOUSE_ID={target['id']}")
            print(f"\n   Add this to config/settings.env:")
            print(f"   FABRIC_LAKEHOUSE_ID={target['id']}")
        else:
            print(f"\n⚠️  Lakehouse '{lakehouse_name}' not found.")
            print("   Create it in Fabric UI: + New item → Lakehouse")
            print(f"   Name it exactly: {lakehouse_name}")

    except Exception as exc:
        print(f"❌ Cannot list lakehouses: {exc}")

    # Check Data Agents availability
    try:
        items_all = _fabric_get(f"/workspaces/{workspace_id}/items", token)
        types = {i.get("type") for i in items_all.get("value", [])}
        if "DataAgent" in types or "Reflex" in types:
            print("\n✅ Data Agent item type available in this workspace")
        else:
            print("\nℹ️  Data Agent items not yet created (expected before Phase 4)")
    except Exception:
        pass


if __name__ == "__main__":
    verify_and_show_ids()
