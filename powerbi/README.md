# Power BI Dashboard — Stewart Title Claims Intelligence

## What's in the .pbix

The `StewartTitle_Claims.pbix` contains 4 report pages connected to
`gold_claims_fraud_scored` via Direct Lake mode:

| Page | Visuals |
|---|---|
| **Executive Summary** | KPI cards: High-risk count, total exposure, avg score, 30-day alerts |
| **Investigator Queue** | Table: open claims by investigator + risk tier breakdown |
| **Fraud Trend** | Line chart: monthly fraud score distribution by risk tier |
| **Claim Deep Dive** | Slicer → drill into individual claim signals + agent audit log |

## Publishing Steps

### 1. Connect to your Fabric Lakehouse

1. Open `StewartTitle_Claims.pbix` in Power BI Desktop
2. **Home → Transform data → Data source settings**
3. Click **Change Source → Microsoft Fabric → Lakehouses**
4. Select workspace `StewartTitle-ClaimsIntelligence`
5. Select lakehouse `stewart_title_claims`
6. Enable table: `gold_claims_fraud_scored`
7. Also add `gold_investigation_audit_log` (created by notebook 03)
8. Click **OK → Close & Apply**

### 2. Verify Direct Lake Mode

In the Model view, click the table — the storage mode should show **Direct Lake**.
If it shows **DirectQuery**, the workspace isn't on F64+ capacity (see DEPLOYMENT.md).

### 3. Publish

1. **Home → Publish**
2. Select `StewartTitle-ClaimsIntelligence` workspace
3. Click **Select**
4. Open in Fabric browser to confirm visuals render

### 4. Set Up Fraud Alert

1. Open the published report in the browser
2. Click the **Open HIGH Risk Claims** KPI card
3. Bell icon → **Set alert**
4. Condition: **Value is above → 0**
5. Email: your claims team distribution list
6. Check "Send me email when condition is true"

### 5. Row-Level Security (Optional — for multi-investigator production use)

In Power BI Desktop before publishing:

1. **Modeling → Manage roles → + New role → "Investigator"**
2. Table: `gold_claims_fraud_scored`
3. DAX filter:
   ```
   [assigned_investigator] = USERPRINCIPALNAME()
   ```
4. Publish updated report
5. In Fabric workspace → Report → **Manage permissions → Add people → assign role**

## Key DAX Measures

These are pre-built in the .pbix:

```dax
// Total HIGH Risk Exposure
High Risk Exposure =
CALCULATE(
    SUMX(gold_claims_fraud_scored, gold_claims_fraud_scored[claim_amount]),
    gold_claims_fraud_scored[risk_tier] = "HIGH",
    gold_claims_fraud_scored[claim_status] IN {"OPEN", "UNDER_REVIEW"}
)

// Claims Needing SAR Filing
SAR Required Count =
CALCULATE(
    COUNTROWS(gold_investigation_audit_log),
    gold_investigation_audit_log[sar_required] = TRUE()
)

// Average Days Open (HIGH risk only)
Avg Days Open HIGH =
CALCULATE(
    AVERAGE(gold_claims_fraud_scored[days_since_filed]),
    gold_claims_fraud_scored[risk_tier] = "HIGH",
    gold_claims_fraud_scored[claim_status] = "OPEN"
)
```
