# Power BI Dashboard — Stewart Title Claims Intelligence

## Important Note on the .pbix File

Power BI Desktop files (`.pbix`) are binary files that must be created in the
Power BI Desktop application — they cannot be generated programmatically.
This directory contains:

- **`README.md`** (this file) — build instructions
- **`report_template.json`** — complete specification of all tables, measures,
  relationships, and visuals so you can recreate the report exactly in ~15 minutes

---

## Step-by-Step Build Guide (~15 minutes)

### 1. Open Power BI Desktop and Connect to Fabric

1. Open Power BI Desktop (download free at powerbi.microsoft.com if needed)
2. **Home → Get data → Microsoft Fabric → Lakehouses**
3. Sign in with your Azure account
4. Navigate: `StewartTitle-ClaimsIntelligence` workspace → `stewart_title_claims`
5. In the Navigator, check these tables:
   - ✅ `gold_claims_fraud_scored`
   - ✅ `gold_investigation_audit_log` *(created after first notebook 03 run)*
6. Click **Load**

> **Connection mode:** Power BI will default to **DirectQuery** locally.
> After publishing to the Fabric workspace (F64+), it automatically upgrades
> to **Direct Lake** mode — no reimport needed.

---

### 2. Create These DAX Measures

In the **Data** pane, right-click `gold_claims_fraud_scored` → **New measure** for each:

```dax
// ── KPI Measures ─────────────────────────────────────────────────────────

Open HIGH Risk Count =
CALCULATE(
    COUNTROWS(gold_claims_fraud_scored),
    gold_claims_fraud_scored[risk_tier] = "HIGH",
    gold_claims_fraud_scored[claim_status] IN {"OPEN", "UNDER_REVIEW"}
)

High Risk Exposure ($) =
CALCULATE(
    SUM(gold_claims_fraud_scored[claim_amount]),
    gold_claims_fraud_scored[risk_tier] = "HIGH",
    gold_claims_fraud_scored[claim_status] IN {"OPEN", "UNDER_REVIEW"}
)

Avg Fraud Score (HIGH) =
CALCULATE(
    AVERAGE(gold_claims_fraud_scored[fraud_risk_score]),
    gold_claims_fraud_scored[risk_tier] = "HIGH"
)

New Alerts (30D) =
CALCULATE(
    COUNTROWS(gold_claims_fraud_scored),
    gold_claims_fraud_scored[primary_alert] <> "NONE",
    gold_claims_fraud_scored[recency_bucket] = "LAST_30D"
)

Avg Days Open (HIGH) =
CALCULATE(
    AVERAGE(gold_claims_fraud_scored[days_since_filed]),
    gold_claims_fraud_scored[risk_tier] = "HIGH",
    gold_claims_fraud_scored[claim_status] = "OPEN"
)

// ── Audit Log Measures (add to gold_investigation_audit_log table) ────────

SAR Required Count =
CALCULATE(
    COUNTROWS(gold_investigation_audit_log),
    gold_investigation_audit_log[sar_required] = TRUE()
)

Payout Hold Count =
CALCULATE(
    COUNTROWS(gold_investigation_audit_log),
    gold_investigation_audit_log[recommended_action] = "PLACE_PAYOUT_HOLD"
)
```

---

### 3. Build the 4 Report Pages

#### Page 1 — Executive Summary

| Visual | Type | Fields | Notes |
|--------|------|--------|-------|
| Open HIGH Risk Claims | Card | `Open HIGH Risk Count` | Red font |
| Total Exposure | Card | `High Risk Exposure ($)` | Format as $M |
| Avg Risk Score | Card | `Avg Fraud Score (HIGH)` | Format as 0.000 |
| New Alerts (30D) | Card | `New Alerts (30D)` | Amber accent |
| Fraud by Type | Donut chart | Legend: `primary_alert`, Values: count | Exclude "NONE" |
| Risk Trend | Line chart | X: `filed_date` (month), Y: count, Legend: `risk_tier` | |
| State Heatmap | Filled map | Location: `state`, Size: `High Risk Exposure ($)` | |

#### Page 2 — Investigator Queue

| Visual | Type | Fields |
|--------|------|--------|
| Claims by Investigator | Bar chart | Y: `assigned_investigator`, X: count, Legend: `risk_tier` |
| Open HIGH Risk Claims Table | Table | `claim_id`, `claim_amount`, `fraud_risk_score`, `primary_alert`, `assigned_investigator`, `filed_date` |
| Risk Tier Slicer | Slicer | `risk_tier` |
| Status Slicer | Slicer | `claim_status` |
| Recency Slicer | Slicer | `recency_bucket` |

Sort the claims table by `fraud_risk_score` descending by default.

#### Page 3 — Fraud Trend Analysis

| Visual | Type | Fields |
|--------|------|--------|
| Monthly Claims by Risk Tier | Stacked column | X: `filed_date` (month), Y: count, Legend: `risk_tier` |
| Signal Breakdown | 100% stacked bar | Y: `primary_alert`, X: avg of each `sig_*` column |
| Velocity Distribution | Histogram (use column chart) | X: `claim_velocity_24mo`, Y: count |
| Exposure by State & Type | Matrix | Rows: `state`, Columns: `claim_type`, Values: sum `claim_amount` |

#### Page 4 — Claim Deep Dive

| Visual | Type | Fields |
|--------|------|--------|
| Claim selector | Slicer | `claim_id` |
| Fraud Signal Radar | Spider/Radar chart | Values: `sig_velocity`, `sig_id_unverified`, `sig_property_spike`, `sig_high_value`, `sig_new_account` |
| Claim Details | Card (multi-row) | `claim_amount`, `fraud_risk_score`, `risk_tier`, `primary_alert`, `assigned_investigator` |
| Investigation Audit | Table (from `gold_investigation_audit_log`) | `recommended_action`, `composite_fraud_probability`, `sar_required`, `investigated_at` |
| Agent Status | Table | `identity_status`, `property_status`, `pattern_status`, `compliance_status` |

---

### 4. Apply Stewart Title Branding

**Theme colors** — Modeling → View → Themes → Customize current theme:

| Color slot | Hex |
|---|---|
| Primary / First data color | `#006341` (Stewart green) |
| Second data color | `#C4963A` (gold accent) |
| Third data color | `#0F4C81` (Fabric blue) |
| Fourth data color | `#6B21A8` (Foundry purple) |
| Diverging high | `#DC2626` (alert red) |
| Background | `#FFFFFF` |
| Card background | `#F7F9F7` |

Font: Calibri throughout.

---

### 5. Set Up Row-Level Security (for production)

**Modeling → Manage roles → + New role: "Investigator"**

Table: `gold_claims_fraud_scored`
DAX filter:
```dax
[assigned_investigator] = USERPRINCIPALNAME()
```

---

### 6. Publish to Fabric

1. **Home → Publish → Select `StewartTitle-ClaimsIntelligence` workspace**
2. In Fabric browser, open the semantic model → verify **Direct Lake** mode
3. Open the report → confirm all 4 pages render

---

### 7. Set Up Fraud Alert

1. Open published report → **Open HIGH Risk Claims** card visual
2. Click bell icon → **Set alert**
3. Condition: **Value is above 0**
4. Send email to: claims team distribution list
5. Check frequency: **At most once per hour**

---

## report_template.json

See `report_template.json` in this directory for the full machine-readable
specification of all measures, relationships, visuals, and color config.
This file can also serve as a handoff document if another team member builds
the report.
