# Deployment Guide
## Stewart Title — Fabric + Foundry Full Stack

> **Estimated setup time:** 45–60 minutes for a first-time deployment  
> **Prerequisites:** See README.md

---

## Table of Contents

1. [Phase 1 — Azure AI Foundry Setup](#phase-1--azure-ai-foundry-setup)
2. [Phase 2 — Microsoft Fabric Workspace](#phase-2--microsoft-fabric-workspace)
3. [Phase 3 — Lakehouse & Notebooks](#phase-3--lakehouse--notebooks)
4. [Phase 4 — Fabric Data Agent](#phase-4--fabric-data-agent)
5. [Phase 5 — Foundry Multi-Agent Registration](#phase-5--foundry-multi-agent-registration)
6. [Phase 6 — Power BI Dashboard](#phase-6--power-bi-dashboard)
7. [Phase 7 — End-to-End Validation](#phase-7--end-to-end-validation)
8. [Production Readiness Checklist](#production-readiness-checklist)
9. [Troubleshooting](#troubleshooting)

---

## Phase 1 — Azure AI Foundry Setup

### 1.1 Create the Foundry Project

1. Go to [https://ai.azure.com](https://ai.azure.com) and sign in
2. Click **+ New project**
3. Fill in:
   - **Project name:** `stewart-title-fraud-detection`
   - **Hub:** Create new or select existing
   - **Region:** `eastus2` (recommended — best model availability)
4. Click **Create**

### 1.2 Deploy GPT-4o

Inside the project:

1. Navigate to **Models + endpoints → Deploy model**
2. Select **gpt-4o** (latest available version)
3. Deployment name: `gpt-4o-fraud`
4. Tokens per minute: `80K` (sufficient for 4 parallel sub-agents)
5. Click **Deploy** and wait ~2 minutes

### 1.3 Grant Fabric Managed Identity Access

This is the key step that allows notebooks to call Foundry without secrets.

```bash
# Get your Fabric workspace Managed Identity Object ID
# (visible in Fabric → Workspace Settings → Identity)
FABRIC_MI_OBJECT_ID="<paste-object-id-here>"

# Get your Foundry project resource ID
# Azure Portal → Resource Groups → your-rg → AI Foundry project → Overview → JSON View
FOUNDRY_RESOURCE_ID="/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.MachineLearningServices/workspaces/stewart-title-fraud-detection"

# Assign Azure AI Developer role
az role assignment create \
  --assignee-object-id "$FABRIC_MI_OBJECT_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Azure AI Developer" \
  --scope "$FOUNDRY_RESOURCE_ID"
```

> **Verify:** In Azure Portal → Foundry project → Access control (IAM) → Role assignments
> You should see the Fabric workspace identity with "Azure AI Developer"

### 1.4 Get the Foundry Endpoint

1. In [ai.azure.com](https://ai.azure.com) → your project → **Overview**
2. Copy the **Project endpoint** — looks like:
   `https://your-hub.services.ai.azure.com/api/projects/stewart-title-fraud-detection`
3. Paste into `config/settings.env` as `FOUNDRY_PROJECT_ENDPOINT`

---

## Phase 2 — Microsoft Fabric Workspace

### 2.1 Create the Workspace

1. Go to [https://app.fabric.microsoft.com](https://app.fabric.microsoft.com)
2. Click **Workspaces → + New workspace**
3. Name: `StewartTitle-ClaimsIntelligence`
4. **License mode:** Select **Fabric** (requires F64+ capacity assigned)
5. Click **Apply**

### 2.2 Assign Fabric Capacity

1. Open workspace **Settings → License info**
2. Click **Edit** → Select your F64+ capacity from the dropdown
3. Click **Save**

> If you don't see your capacity, confirm it's active in the Azure Portal under
> **Microsoft Fabric capacities** and that you have admin rights on it.

### 2.3 Enable Workspace Identity (Managed Identity)

1. Workspace **Settings → Identity**
2. Toggle **On** for "Workspace identity"
3. Copy the **Object ID** — needed for Phase 1.3 above

### 2.4 Copy Workspace ID

1. In the browser URL when viewing the workspace:
   `https://app.fabric.microsoft.com/groups/<WORKSPACE-ID>/...`
2. Copy that GUID → paste into `config/settings.env` as `FABRIC_WORKSPACE_ID`

---

## Phase 3 — Lakehouse & Notebooks

### 3.1 Create the Lakehouse

1. Inside your workspace, click **+ New item → Lakehouse**
2. Name: `stewart_title_claims`
3. Click **Create**
4. Copy the Lakehouse ID from the URL and paste into `config/settings.env`

### 3.2 Configure settings.env

```bash
cp config/settings.env.example config/settings.env
```

Edit `config/settings.env`:

```bash
# Azure AI Foundry
FOUNDRY_PROJECT_ENDPOINT=https://your-hub.services.ai.azure.com/api/projects/stewart-title-fraud-detection
FOUNDRY_MODEL_DEPLOYMENT=gpt-4o-fraud

# Microsoft Fabric
FABRIC_WORKSPACE_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
FABRIC_LAKEHOUSE_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
FABRIC_LAKEHOUSE_NAME=stewart_title_claims

# Optional: for local testing with a service principal instead of MI
# AZURE_CLIENT_ID=
# AZURE_CLIENT_SECRET=
# AZURE_TENANT_ID=
```

### 3.3 Upload Notebooks to Fabric

```bash
python scripts/upload_notebooks.py
```

This script:
- Reads each `.ipynb` from `notebooks/`
- Calls the Fabric REST API to create/update the notebook item
- Attaches the default lakehouse to each notebook

**Manual alternative:**
1. In Fabric workspace → **+ New item → Notebook**
2. Click the three-dot menu on the notebook → **Import notebook**
3. Upload each `.ipynb` file from the `notebooks/` directory
4. For each notebook: click **Add lakehouse** → select `stewart_title_claims`

### 3.4 Run Notebooks in Order

Run each notebook sequentially — either from the Fabric UI or via the API:

```bash
# Trigger via Fabric REST API (runs in Fabric Spark, not locally)
python scripts/run_notebooks_sequence.py
```

**Manual:** Open each notebook in Fabric and click **Run all**

| Notebook | Runtime | What it builds |
|---|---|---|
| `01_bronze_ingest.ipynb` | ~2 min | 3 Bronze Delta tables, 1,200 synthetic claims |
| `02_silver_enrich.ipynb` | ~2 min | Velocity features, derived columns |
| `03_gold_fraud_score.ipynb` | ~3 min | Scored Gold table, Z-ORDER optimized |
| `04_validate_pipeline.ipynb` | ~1 min | Row counts, NULL checks, score distribution |

> **Expected output of 04:** All checks should show ✅. If any show ⚠️, see Troubleshooting.

---

## Phase 4 — Fabric Data Agent

### 4.1 Create the Data Agent

1. In Fabric workspace → **+ New item → Data agent** (under AI + Analytics)
2. Name: `StewartTitle-ClaimsAgent`

> If you don't see "Data agent" in the menu, verify your workspace is on F64+
> capacity and that Data Agent preview is enabled in your tenant admin settings.

### 4.2 Add the Data Source

1. Inside the agent editor → **+ Add data source**
2. Select **Lakehouse**
3. Choose `stewart_title_claims`
4. Under **Tables**, enable:
   - ✅ `gold_claims_fraud_scored`
   - ✅ `silver_claims_enriched` (optional — for velocity deep dives)
5. Click **Save**

### 4.3 Configure the System Instructions

1. Click **Instructions** tab in the agent editor
2. Paste the contents of `config/data_agent_config.json` → `system_prompt` field
3. Click **Save**

### 4.4 Test the Agent

In the agent chat window, try these queries:

```
Show me all open HIGH risk claims filed in the last 90 days
```
```
Which claimants have filed more than 2 claims in 24 months?
```
```
What is the total exposure on unresolved wire fraud alerts by state?
```

Each response should show the SQL used (Verified Answers mode). If the agent
returns "I can't find that information," check that the Gold table has rows
(`SELECT COUNT(*) FROM gold_claims_fraud_scored`).

### 4.5 Copy the Agent ID

1. In the Fabric URL when viewing the agent:
   `https://app.fabric.microsoft.com/groups/<workspace>/dataagentedit/<AGENT-ID>`
2. Copy the Agent ID → paste into `config/settings.env` as `FABRIC_AGENT_ID`

---

## Phase 5 — Foundry Multi-Agent Registration

### 5.1 Install Python Dependencies

```bash
pip install -r agents/requirements.txt
```

### 5.2 Register All Four Sub-Agents

```bash
python scripts/provision_foundry.py
```

This script:
- Connects to your Foundry project using `DefaultAzureCredential` (picks up
  your `az login` session locally, or Managed Identity in Fabric)
- Creates 4 specialized agents with their system prompts
- Creates the orchestrator agent that references the sub-agents
- Writes agent IDs to `config/agent_ids.json`

**Verify in Foundry UI:**
1. [ai.azure.com](https://ai.azure.com) → your project → **Agents**
2. You should see 5 agents: 4 specialists + 1 orchestrator

### 5.3 Test the Multi-Agent Flow Locally

```bash
# Requires az login or AZURE_* env vars set
python agents/trigger.py --claim-id CLM-2024-7734 --dry-run
```

Expected output:
```
🚀 Orchestrator invoked for claim: CLM-2024-7734
  [Agent 1] Identity Verification Agent → FLAGGED
  [Agent 2] Property History Agent → ANOMALY_DETECTED
  [Agent 3] Claims Pattern Agent → MATCH_FOUND
  [Agent 4] Regulatory Compliance Agent → SAR_REQUIRED
  ✅ Report written to: investigation_reports/CLM-2024-7734.json
```

### 5.4 Wire Notebook Trigger → Foundry

The Gold scoring notebook (03) automatically calls `trigger.py` for any claim
with `fraud_risk_score > 0.75 AND claim_status = 'OPEN'`. This is implemented
in the last cell of `03_gold_fraud_score.ipynb`.

The trigger runs as the workspace Managed Identity — no credentials needed inside
the notebook.

---

## Phase 6 — Power BI Dashboard

### 6.1 Open in Power BI Desktop

1. Open `powerbi/StewartTitle_Claims.pbix` in Power BI Desktop
2. You'll see placeholder visuals — we'll connect them to your Fabric data

### 6.2 Connect to Fabric (Direct Lake)

1. In Power BI Desktop → **Home → Transform data → Data source settings**
2. Click **Change Source**
3. Select **Microsoft Fabric** → **Lakehouses**
4. Navigate to your workspace → `stewart_title_claims`
5. Select the `gold_claims_fraud_scored` table
6. Click **OK → Close & Apply**

> **Important:** Direct Lake only works when published to a Premium/Fabric workspace.
> Local preview in Desktop will use DirectQuery fallback — this is normal.

### 6.3 Publish to Fabric

1. **Home → Publish**
2. Select your `StewartTitle-ClaimsIntelligence` workspace
3. Click **Select**

### 6.4 Configure Row-Level Security (Optional for Demo)

To show investigators only their assigned claims:

1. In Power BI Desktop → **Modeling → Manage roles**
2. Create role: `Investigator`
3. Table: `gold_claims_fraud_scored`
4. DAX filter: `[assigned_investigator] = USERPRINCIPALNAME()`
5. Publish the updated report

### 6.5 Set Up Fraud Alert

1. In the published report → open the **High Risk Claims** visual
2. Click the bell icon → **Set alert**
3. Condition: **Value exceeds 0** (triggers when any HIGH risk open claim appears)
4. Email: your claims team distribution list

---

## Phase 7 — End-to-End Validation

```bash
python scripts/validate_deployment.py
```

This runs 8 checks and reports pass/fail:

| Check | What It Tests |
|---|---|
| Fabric API connectivity | Workspace is reachable and authenticated |
| Lakehouse tables | All 5 tables exist with expected row counts |
| Gold table schema | All required columns present, no NULLs in key fields |
| Fraud score distribution | Score range 0–1, HIGH tier ≥ 5% of claims |
| Data Agent | Agent responds to a test NL query |
| Foundry connectivity | Orchestrator agent is registered and reachable |
| Agent handoff | Test claim triggers all 4 sub-agents without error |
| Power BI | Report published and refreshable (API check) |

All 8 ✅ = you're ready to demo.

---

## Production Readiness Checklist

Before using with real Stewart Title data:

### Data & Security
- [ ] Replace synthetic data with Fabric Mirroring from production claims SQL Server
- [ ] Enable Fabric workspace-level encryption (Microsoft-managed or CMK)
- [ ] Configure Purview data classification on PII columns (SSN, names)
- [ ] Apply row-level security on Gold table by investigator assignment
- [ ] Enable Fabric Audit Logs → export to Log Analytics workspace

### AI & Agent Safety  
- [ ] Replace simulated sub-agent logic with real data lookups (public records APIs,
      your internal property DB, claims history warehouse)
- [ ] Add content filters on Foundry model deployment (Azure AI Content Safety)
- [ ] Implement human-in-the-loop approval before any payout hold action
- [ ] Log all agent invocations and outputs to the Lakehouse `agent_audit_log` table
- [ ] Set token quotas per agent to prevent runaway costs

### Operations
- [ ] Schedule notebook refresh (Fabric pipeline: daily at 2am)
- [ ] Set up Power BI scheduled refresh (Direct Lake = auto, no schedule needed)
- [ ] Configure Fabric capacity auto-pause during off-hours
- [ ] Create alerts on notebook failures (Fabric Monitoring Hub → email notification)
- [ ] Document agent prompt versions in `config/` and version-control changes

---

## Troubleshooting

### "Data Agent item type not found in workspace"
Your capacity is below F64, or the Data Agents preview feature isn't enabled.
- Check: Fabric Admin Portal → Tenant settings → "Data Agents (preview)"
- Ensure it's enabled for your tenant or specific security group

### "ManagedIdentityCredential authentication failed" in notebooks
The workspace identity isn't provisioned or the role assignment from Phase 1.3
hasn't propagated yet (can take up to 15 minutes).
- Verify in Azure Portal → Foundry project → IAM → Role assignments
- Re-run the `az role assignment create` command and wait 10 minutes

### Gold table row count is 0 after running notebooks
Notebook 01 or 02 failed silently.
- Open the Fabric Monitoring Hub → find the notebook run → check logs
- Common cause: wrong default lakehouse attached. Re-attach `stewart_title_claims`

### Foundry agent returns empty responses
The GPT-4o deployment is rate-limited or the endpoint URL is wrong.
- Check `config/settings.env` — endpoint must end with the project name path
- In ai.azure.com → Deployments — verify `gpt-4o-fraud` shows "Succeeded"
- Check quota: 80K TPM should be sufficient; request increase if shared with other projects

### Power BI shows "DirectQuery" instead of "Direct Lake"
Report is not published to a Fabric workspace with F64+ capacity.
- Republish to the `StewartTitle-ClaimsIntelligence` workspace
- Verify that workspace is on F64+ capacity (Workspace Settings → License)
