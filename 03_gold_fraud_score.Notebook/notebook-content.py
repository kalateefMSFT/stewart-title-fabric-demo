# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "e87eaff5-ed7c-4955-a186-d62849879068",
# META       "default_lakehouse_name": "stewart_title_claims",
# META       "default_lakehouse_workspace_id": "014dbc16-1b53-47bf-a4f4-e72029021280",
# META       "known_lakehouses": [
# META         {
# META           "id": "e87eaff5-ed7c-4955-a186-d62849879068"
# META         }
# META       ]
# META     }
# META   }
# META }

# MARKDOWN ********************

# # 03 — Gold Layer: Fraud Scoring + Foundry Trigger
# **Purpose:** Apply fraud risk model, write Gold table, trigger Foundry multi-agent for HIGH risk claims.
# 
# **Output:** `gold_claims_fraud_scored` (Z-ORDER optimized, Data Agent target)
# 
# > **Fabric IQ Demo Moment:** In Cell 2, highlight the scoring logic and say:
# > *'This is the kind of PySpark Fabric IQ Copilot generates from a plain-English description of your fraud signals.'*

# CELL ********************

from pyspark.sql import SparkSession, functions as F
import os

spark = SparkSession.builder.getOrCreate()

# Tunable thresholds — match config/settings.env
HIGH_THRESHOLD   = float(os.environ.get('FRAUD_HIGH_THRESHOLD',   '0.75'))
MEDIUM_THRESHOLD = float(os.environ.get('FRAUD_MEDIUM_THRESHOLD', '0.45'))
ALERT_AMOUNT_MIN = float(os.environ.get('FRAUD_ALERT_AMOUNT_MIN', '50000'))

print(f'Thresholds — HIGH: {HIGH_THRESHOLD} | MEDIUM: {MEDIUM_THRESHOLD} | Min amount: ${ALERT_AMOUNT_MIN:,.0f}')

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# ── Fraud Risk Scoring ────────────────────────────────────────────────────
# Six weighted signals → composite fraud_risk_score (0–0.99)
# Weights tuned for title insurance domain; adjust in Phase 2 with ML

silver = spark.table('silver_claims_enriched')

scored = (
    silver
    # Individual signals (each 0.0–1.0)
    .withColumn('sig_velocity',
        F.least(F.lit(1.0),
            ((F.col('claim_velocity_24mo') - 1).cast('double') / F.lit(4.0))).cast('double'))
    .withColumn('sig_id_unverified',
        F.when(F.col('id_verified') == False, F.lit(1.0)).otherwise(F.lit(0.0)))
    .withColumn('sig_property_spike',
        F.when(F.col('value_pct_change') > 40.0, F.lit(1.0))
         .when(F.col('value_pct_change') > 20.0, F.lit(0.65))
         .otherwise(F.lit(0.0)))
    .withColumn('sig_high_value',
        F.when(F.col('claim_amount') > 250_000, F.lit(1.0))
         .when(F.col('claim_amount') > 100_000, F.lit(0.55))
         .otherwise(F.lit(0.0)))
    .withColumn('sig_new_account',
        F.when(F.col('account_age_days') < 180, F.lit(0.8))
         .when(F.col('account_age_days') < 365, F.lit(0.4))
         .otherwise(F.lit(0.0)))
    .withColumn('sig_lien',
        F.when(F.col('has_lien') == True, F.lit(0.6)).otherwise(F.lit(0.0)))
    # Weighted composite score
    .withColumn('fraud_risk_score',
        F.round(F.least(F.lit(0.99), (
            F.col('sig_velocity')       * F.lit(0.30) +
            F.col('sig_id_unverified')  * F.lit(0.28) +
            F.col('sig_property_spike') * F.lit(0.20) +
            F.col('sig_high_value')     * F.lit(0.12) +
            F.col('sig_new_account')    * F.lit(0.06) +
            F.col('sig_lien')           * F.lit(0.04)
        )), 3))
    .withColumn('risk_tier',
        F.when(F.col('fraud_risk_score') >= HIGH_THRESHOLD,   F.lit('HIGH'))
         .when(F.col('fraud_risk_score') >= MEDIUM_THRESHOLD, F.lit('MEDIUM'))
         .otherwise(F.lit('LOW')))
    .withColumn('primary_alert',
        F.when((F.col('sig_id_unverified') >= 0.8) & (F.col('risk_tier') == 'HIGH'),
               F.lit('IDENTITY_VERIFICATION_REQUIRED'))
         .when((F.col('sig_velocity') >= 0.75) & (F.col('risk_tier') == 'HIGH'),
               F.lit('ABNORMAL_CLAIM_VELOCITY'))
         .when((F.col('sig_property_spike') >= 0.65) & F.col('risk_tier').isin('HIGH','MEDIUM'),
               F.lit('PROPERTY_VALUE_ANOMALY'))
         .when(F.col('risk_tier') == 'HIGH', F.lit('MULTI_SIGNAL_FRAUD_RISK'))
         .otherwise(F.lit('NONE')))
    .withColumn('scored_at', F.current_timestamp())
)

# Write Gold table
gold_cols = [
    'claim_id','claimant_id','property_id','state','claim_type','claim_amount',
    'claim_status','filed_date','resolved_date','assigned_investigator',
    'recency_bucket','days_since_filed','fraud_risk_score','risk_tier','primary_alert',
    'sig_velocity','sig_id_unverified','sig_property_spike','sig_high_value','sig_new_account',
    'claim_velocity_24mo','id_verified','value_pct_change','has_lien','account_age_days',
    'is_confirmed_fraud','fraud_label','scored_at'
]

(
    scored.select(*gold_cols)
    .write.format('delta')
    .mode('overwrite')
    .option('overwriteSchema', 'true')
    .saveAsTable('gold_claims_fraud_scored')
)

# Z-ORDER for agent query performance
spark.sql('OPTIMIZE gold_claims_fraud_scored ZORDER BY (risk_tier, filed_date, fraud_risk_score)')

# Summary
spark.sql('''
    SELECT risk_tier, COUNT(*) AS claims, ROUND(AVG(fraud_risk_score),3) AS avg_score,
           ROUND(SUM(claim_amount)/1e6,2) AS exposure_M
    FROM gold_claims_fraud_scored GROUP BY risk_tier ORDER BY avg_score DESC
''').show()

print('✅ gold_claims_fraud_scored written and optimized')

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# ── Trigger Foundry Multi-Agent for HIGH Risk Claims ──────────────────────
# Uses Workspace Managed Identity — no credentials needed here

# Add the repo root to sys.path so agents/ can be imported
import sys
sys.path.insert(0, '/lakehouse/default/Files/stewart-title-fabric-demo')

from agents.trigger import run_pending_investigations

run_pending_investigations(
    spark=spark,
    dry_run=False   # Set True to skip Foundry calls during notebook testing
)

print('\n✅ Investigation reports written to gold_investigation_audit_log')
print('   Run 04_validate_pipeline.ipynb to confirm all checks pass.')

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
