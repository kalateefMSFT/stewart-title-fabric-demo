"""
Azure AI Foundry client wrapper.

Authentication priority:
  1. Managed Identity (when running inside Fabric notebooks / Azure)
  2. DefaultAzureCredential chain (az login, env vars, etc.) for local dev

Usage:
    client = get_foundry_client()
    agent  = client.agents.get_agent(agent_id)
"""

from __future__ import annotations

import os
import logging
from functools import lru_cache
from typing import Optional

from azure.core.credentials import AccessToken, TokenCredential
from azure.ai.projects import AIProjectClient
from azure.identity import (
    AzureCliCredential,
    AzureDeveloperCliCredential,
    AzurePowerShellCredential,
    ChainedTokenCredential,
    DefaultAzureCredential,
    ManagedIdentityCredential,
    SharedTokenCacheCredential,
    VisualStudioCodeCredential,
)

logger = logging.getLogger(__name__)


def _load_env() -> dict[str, str]:
    """Load settings from config/settings.env if present (local dev only)."""
    env_path = os.path.join(os.path.dirname(__file__), "..", "config", "settings.env")
    settings: dict[str, str] = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    settings[k.strip()] = v.strip()
    return settings


class _FallbackCredential(TokenCredential):
    """Try managed identity first, then fall back to developer credentials."""

    def __init__(self, primary: TokenCredential, fallback: TokenCredential):
        self._primary = primary
        self._fallback = fallback

    def get_token(self, *scopes, **kwargs) -> AccessToken:
        try:
            return self._primary.get_token(*scopes, **kwargs)
        except Exception as primary_error:
            logger.warning(
                "Managed identity token acquisition failed; falling back to DefaultAzureCredential: %s",
                primary_error,
            )
            return self._fallback.get_token(*scopes, **kwargs)

    def get_token_info(self, *scopes, **kwargs):
        try:
            return self._primary.get_token_info(*scopes, **kwargs)
        except Exception as primary_error:
            logger.warning(
                "Managed identity token acquisition failed; falling back to DefaultAzureCredential: %s",
                primary_error,
            )
            return self._fallback.get_token_info(*scopes, **kwargs)


def _build_developer_credential() -> TokenCredential:
    """Build a broad local-dev credential chain."""
    return ChainedTokenCredential(
        AzureCliCredential(),
        AzureDeveloperCliCredential(),
        AzurePowerShellCredential(),
        VisualStudioCodeCredential(),
        SharedTokenCacheCredential(),
        DefaultAzureCredential(),
    )


def _get_credential():
    """
    Return the best available credential.

    Inside a Fabric notebook the workspace Managed Identity is available
    automatically via ManagedIdentityCredential.  Locally, DefaultAzureCredential
    walks the standard chain (env vars → az login → VS Code → etc.).
    """
    # Prefer explicit MI client ID if set (user-assigned MI scenario)
    mi_client_id = os.environ.get("AZURE_CLIENT_ID")

    # Detect if we're running inside Azure (Fabric / ACI / App Service)
    in_azure = os.environ.get("MSI_ENDPOINT") or os.environ.get("IDENTITY_ENDPOINT")

    force_local = os.environ.get("AZURE_FOUNDRY_FORCE_LOCAL_CREDENTIALS", "").lower() in {"1", "true", "yes"}

    if force_local:
        logger.info("AZURE_FOUNDRY_FORCE_LOCAL_CREDENTIALS set — using developer credential chain")
        return _build_developer_credential()

    if in_azure:
        logger.info("Running in Azure — using ManagedIdentityCredential")
        managed_identity = (
            ManagedIdentityCredential(client_id=mi_client_id)
            if mi_client_id
            else ManagedIdentityCredential()
        )
        return _FallbackCredential(managed_identity, _build_developer_credential())

    logger.info("Running locally — using developer credential chain")
    return _build_developer_credential()


@lru_cache(maxsize=1)
def get_foundry_client(endpoint: Optional[str] = None) -> AIProjectClient:
    """
    Return a cached AIProjectClient connected to the Foundry project.

    Args:
        endpoint: Foundry project endpoint URL. Falls back to FOUNDRY_PROJECT_ENDPOINT
                  env var or settings.env.

    Returns:
        AIProjectClient ready for agents.get_agent(), agents.create_run(), etc.
    """
    env = _load_env()

    resolved_endpoint = (
        endpoint
        or os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
        or env.get("FOUNDRY_PROJECT_ENDPOINT")
    )

    if not resolved_endpoint:
        raise ValueError(
            "FOUNDRY_PROJECT_ENDPOINT not set. "
            "Add it to config/settings.env or set the environment variable."
        )

    credential = _get_credential()

    client = AIProjectClient(
        endpoint=resolved_endpoint,
        credential=credential,
    )

    logger.info("AIProjectClient created for endpoint: %s", resolved_endpoint)
    return client


def get_agent_ids(env: Optional[dict] = None) -> dict[str, str]:
    """
    Load agent IDs from environment / settings.env.
    These are written by provision_foundry.py after initial setup.
    """
    if env is None:
        env = _load_env()

    required = {
        "orchestrator":    "AGENT_ID_ORCHESTRATOR",
        "identity":        "AGENT_ID_IDENTITY",
        "property":        "AGENT_ID_PROPERTY",
        "claims_pattern":  "AGENT_ID_CLAIMS_PATTERN",
        "compliance":      "AGENT_ID_COMPLIANCE",
    }

    ids: dict[str, str] = {}
    missing: list[str] = []

    for key, env_key in required.items():
        val = os.environ.get(env_key) or env.get(env_key, "")
        if val:
            ids[key] = val
        else:
            missing.append(env_key)

    if missing:
        raise RuntimeError(
            f"Missing agent IDs: {missing}. "
            "Run `python scripts/provision_foundry.py` first."
        )

    return ids
