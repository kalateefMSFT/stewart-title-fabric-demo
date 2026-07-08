"""
upload_notebooks.py

Uploads all notebooks from notebooks/ to the Fabric workspace via REST API,
then attaches the default lakehouse to each one.

Usage:
    python scripts/upload_notebooks.py [--notebook 03_gold_fraud_score]
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import urllib.request
from pathlib import Path
from time import sleep

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.foundry_client import _load_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

FABRIC_API_BASE = "https://api.fabric.microsoft.com/v1"
NOTEBOOKS_DIR   = Path(__file__).parent.parent / "notebooks"


def _get_token() -> str:
    from azure.identity import DefaultAzureCredential
    return DefaultAzureCredential().get_token(
        "https://api.fabric.microsoft.com/.default"
    ).token


def _fabric_request(method: str, path: str, body: dict | None, token: str) -> dict:
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
        body_text = e.read().decode()
        raise RuntimeError(f"HTTP {e.code} {method} {path}: {body_text}") from e


def _inject_workspace_id(nb_content: dict, workspace_id: str, lakehouse_id: str) -> dict:
    """Replace placeholder IDs in notebook metadata."""
    nb_str = json.dumps(nb_content)
    nb_str = nb_str.replace("<FABRIC_WORKSPACE_ID>", workspace_id)
    nb_str = nb_str.replace("<FABRIC_LAKEHOUSE_ID>", lakehouse_id)
    return json.loads(nb_str)


def upload_notebook(nb_path: Path, workspace_id: str, lakehouse_id: str, token: str):
    """Upload or update a single notebook in the Fabric workspace."""
    nb_name  = nb_path.stem   # e.g. "01_bronze_ingest"
    nb_content = json.loads(nb_path.read_text())

    # Inject real IDs
    nb_content = _inject_workspace_id(nb_content, workspace_id, lakehouse_id)

    # Check if notebook already exists
    existing = _fabric_request("GET", f"/workspaces/{workspace_id}/items?type=Notebook", None, token)
    existing_item = next(
        (i for i in existing.get("value", []) if i.get("displayName") == nb_name),
        None,
    )

    # Encode notebook as base64
    nb_b64 = base64.b64encode(json.dumps(nb_content).encode()).decode()

    if existing_item:
        item_id = existing_item["id"]
        logger.info("Updating existing notebook: %s (%s)", nb_name, item_id)
        _fabric_request("PATCH", f"/workspaces/{workspace_id}/items/{item_id}", {
            "definition": {
                "format": "ipynb",
                "parts": [{"path": "notebook-content.py", "payload": nb_b64, "payloadType": "InlineBase64"}]
            }
        }, token)
    else:
        logger.info("Creating notebook: %s", nb_name)
        result = _fabric_request("POST", f"/workspaces/{workspace_id}/items", {
            "displayName": nb_name,
            "type":        "Notebook",
            "definition": {
                "format": "ipynb",
                "parts": [{"path": "notebook-content.py", "payload": nb_b64, "payloadType": "InlineBase64"}]
            }
        }, token)
        item_id = result.get("id")

    logger.info("  ✅ %s uploaded (ID: %s)", nb_name, item_id)
    return item_id


def upload_all(filter_name: str | None = None):
    env = _load_env()

    workspace_id  = env.get("FABRIC_WORKSPACE_ID", "").strip()
    lakehouse_id  = env.get("FABRIC_LAKEHOUSE_ID",  "").strip()

    if not workspace_id or workspace_id.startswith("xxx"):
        print("❌ FABRIC_WORKSPACE_ID not set. Run setup_fabric.py first.")
        sys.exit(1)
    if not lakehouse_id or lakehouse_id.startswith("xxx"):
        print("❌ FABRIC_LAKEHOUSE_ID not set. Run setup_fabric.py first.")
        sys.exit(1)

    token = _get_token()
    notebooks = sorted(NOTEBOOKS_DIR.glob("*.ipynb"))

    if filter_name:
        notebooks = [nb for nb in notebooks if filter_name in nb.stem]
        if not notebooks:
            print(f"No notebooks matching '{filter_name}'")
            sys.exit(1)

    print(f"Uploading {len(notebooks)} notebook(s) to workspace {workspace_id}...")

    for nb_path in notebooks:
        try:
            upload_notebook(nb_path, workspace_id, lakehouse_id, token)
            sleep(0.5)   # rate limiting
        except Exception as exc:
            logger.error("Failed to upload %s: %s", nb_path.name, exc)
            raise

    print(f"\n✅ {len(notebooks)} notebook(s) uploaded.")
    print("   Open Fabric workspace → run notebooks in order: 01 → 02 → 03 → 04")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload notebooks to Fabric")
    parser.add_argument("--notebook", default=None,
                        help="Upload only notebooks matching this name substring")
    args = parser.parse_args()
    upload_all(filter_name=args.notebook)
