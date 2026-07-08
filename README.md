# Stewart Title — Intelligent Claims & Fraud Detection
### Microsoft Fabric + Azure AI Foundry | Full-Stack Demo

[![Fabric](https://img.shields.io/badge/Microsoft%20Fabric-F64%2B-0078D4?logo=microsoft)](https://fabric.microsoft.com)
[![Foundry](https://img.shields.io/badge/Azure%20AI%20Foundry-Multi--Agent-00B4D8?logo=azure)](https://ai.azure.com)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python)](https://python.org)

---

## What This Repo Deploys

```
Claims Data (SQL/CSV)
        │
        ▼
┌─────────────────────────────────────────────────────┐
│              Microsoft Fabric Workspace              │
│                                                     │
│  Lakehouse (OneLake)                                │
│    bronze_claims_raw  ──► silver_claims_enriched    │
│                                ──► gold_claims_fraud_scored  ◄── Data Agent
│                                                     │
│  Fabric Notebooks (PySpark)                         │
│    01_ingest.ipynb  02_score.ipynb  03_validate.ipynb│
│                                                     │
│  Fabric Data Agent                                  │
│    NL → SQL over gold table                         │
└─────────────────────────────────────────────────────┘
        │  fraud_risk_score > 0.75
        ▼
┌─────────────────────────────────────────────────────┐
│              Azure AI Foundry Project               │
│                                                     │
│  Orchestrator Agent                                 │
│    ├─► Identity Verification Agent                  │
│    ├─► Property History Agent                       │
│    ├─► Claims Pattern Agent                         │
│    └─► Regulatory Compliance Agent                  │
│                                                     │
│  Output → investigation_reports/ in OneLake         │
└─────────────────────────────────────────────────────┘
        │
        ▼
  Power BI Dashboard (Direct Lake)
  Claims Risk KPIs · Investigator Queue · Fraud Trend
```

---

## Prerequisites

| Requirement | Version / SKU | Notes |
|---|---|---|
| Microsoft Fabric | F64 or higher | F64 minimum for Direct Lake + Data Agents |
| Azure AI Foundry | Standard tier | GPT-4o deployment required |
| Azure CLI | 2.60+ | `az login` before running scripts |
| Python | 3.10+ | For local agent testing |
| Power BI Desktop | Latest | For `.pbix` publishing |

### Required Azure Permissions
- **Fabric:** Workspace Admin
- **Azure:** `Contributor` on the resource group + `Cognitive Services OpenAI Contributor`
- **Entra ID:** Ability to create App Registrations (or have one created for you)

---

## Repo Structure

```
stewart-title-fabric-demo/
├── README.md                          ← You are here
├── DEPLOYMENT.md                      ← Step-by-step manual setup guide
├── config/
│   ├── settings.env.example           ← Copy → settings.env, fill in values
│   ├── fabric_workspace.json          ← Workspace metadata template
│   └── data_agent_config.json         ← Data Agent system prompt + schema
├── notebooks/
│   ├── 01_bronze_ingest.ipynb         ← Data ingestion → Bronze layer
│   ├── 02_silver_enrich.ipynb         ← Feature engineering → Silver layer
│   ├── 03_gold_fraud_score.ipynb      ← Fraud scoring → Gold layer (Agent target)
│   └── 04_validate_pipeline.ipynb     ← Data quality checks + row counts
├── agents/
│   ├── foundry_client.py              ← AIProjectClient wrapper (Managed Identity)
│   ├── orchestrator.py                ← Orchestrator agent — dispatches sub-agents
│   ├── sub_agents/
│   │   ├── identity_agent.py          ← Identity verification specialist
│   │   ├── property_agent.py          ← Property history specialist
│   │   ├── claims_pattern_agent.py    ← Fraud pattern matching specialist
│   │   └── compliance_agent.py        ← Regulatory (SAR/ALTA) specialist
│   ├── models.py                      ← Pydantic models for agent I/O
│   ├── trigger.py                     ← Fabric notebook trigger → Foundry handoff
│   └── requirements.txt               ← Python dependencies
├── scripts/
│   ├── setup_fabric.py                ← Fabric REST API: create workspace/lakehouse
│   ├── upload_notebooks.py            ← Upload .ipynb files via Fabric API
│   ├── register_data_agent.py         ← Configure Fabric Data Agent via API
│   ├── provision_foundry.py           ← Create Foundry project + register agents
│   └── validate_deployment.py         ← End-to-end health check
├── powerbi/
│   ├── StewartTitle_Claims.pbix       ← Power BI Desktop file (Direct Lake)
│   └── README.md                      ← Power BI publishing instructions
└── .github/
    └── workflows/
        └── validate.yml               ← PR validation: lint + agent unit tests
```

---

## Quick Start (30 minutes)

Follow **[DEPLOYMENT.md](DEPLOYMENT.md)** for the full walkthrough. Summary:

```bash
# 1. Clone and configure
git clone https://github.com/your-org/stewart-title-fabric-demo
cd stewart-title-fabric-demo
cp config/settings.env.example config/settings.env
# → Edit settings.env with your values

# 2. Install Python deps (local testing)
pip install -r agents/requirements.txt

# 3. Provision Azure AI Foundry resources
python scripts/provision_foundry.py

# 4. Set up Fabric workspace (creates lakehouse + uploads notebooks)
python scripts/setup_fabric.py
python scripts/upload_notebooks.py

# 5. Run notebooks in order (in Fabric UI or via API)
#    01 → 02 → 03 → 04

# 6. Register the Data Agent
python scripts/register_data_agent.py

# 7. Validate end-to-end
python scripts/validate_deployment.py

# 8. Publish Power BI report
#    See powerbi/README.md
```

---

## Architecture Decisions

### Why Managed Identity (not API keys)?
Fabric notebooks run as the workspace's Managed Identity. By assigning this identity
`Azure AI Developer` role on the Foundry project, notebooks can call agents without
any secrets in code or Key Vault lookups during the demo. Production deployments
should use a dedicated service principal with narrower scope.

### Why Gold → Data Agent (not Silver)?
The Data Agent's NL→SQL grounding is most reliable on a wide, denormalized table
with consistent column naming and no NULLs in key filter columns. Gold satisfies this.
Silver is narrower and optimized for pipeline efficiency, not ad-hoc querying.

### Why F64 minimum?
Direct Lake mode (used by the Power BI report) requires F64+. F32 will work for
everything else (notebooks, Data Agent, Foundry integration) but the Power BI
dashboard will fall back to Import mode, which requires a scheduled refresh.

---

## Support & Customization

- **Custom fraud signals:** Edit `notebooks/03_gold_fraud_score.ipynb` Cell 3 weights
- **Agent prompts:** See `config/data_agent_config.json` and `agents/sub_agents/*.py`
- **Different data source:** Replace `notebooks/01_bronze_ingest.ipynb` with your
  Fabric Mirroring or ADF pipeline; Silver/Gold notebooks are source-agnostic
- **Production hardening checklist:** See `DEPLOYMENT.md#production-readiness`
