# Fabric notebook source

# METADATA ********************

# META {
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse_name": "stewart_title_claims",
# META       "default_lakehouse_workspace_id": "<FABRIC_WORKSPACE_ID>"
# META     }
# META   }
# META }

# MARKDOWN ********************

# # 04 — Pipeline Validation
# **Purpose:** Automated data quality checks across all layers.
# All checks must show ✅ before the demo. Any ⚠️ indicates a pipeline issue.

# CELL ********************

# Resolve repo root dynamically so local and Fabric runs can import project packages.
import sys
from pathlib import Path

def _find_repo_root() -> Path | None:
    candidates = [
        Path.cwd(),
        Path('/lakehouse/default/Files/stewart-title-fabric-demo'),
    ]
    for start in candidates:
        if not start.exists():
            continue
        for current in [start.resolve(), *start.resolve().parents]:
            if (current / 'agents' / '__init__.py').exists():
                return current
    return None

repo_root = _find_repo_root()
if repo_root and str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
    print(f'Project root added to sys.path: {repo_root}')

# CELL ********************

from pyspark.sql import SparkSession, functions as F

spark = SparkSession.builder.getOrCreate()
issues = []

def check(name, condition, detail=''):
    icon = '✅' if condition else '⚠️  FAIL'
    print(f'  {icon}  {name}' + (f' — {detail}' if detail else ''))
    if not condition:
        issues.append(name)

print('=' * 55)
print('PIPELINE VALIDATION REPORT')
print('=' * 55)

# ── Table existence + row counts ──────────────────────────────────────────
print('\n[1] Table Row Counts')
tables = {
    'bronze_claims_raw':       (1000, 2000),
    'bronze_claimants':        (300,  500),
    'bronze_properties':       (600,  1000),
    'silver_claims_enriched':  (1000, 2000),
    'gold_claims_fraud_scored': (1000, 2000),
}
for tbl, (lo, hi) in tables.items():
    try:
        n = spark.table(tbl).count()
        check(tbl, lo <= n <= hi, f'{n:,} rows')
    except Exception as e:
        check(tbl, False, f'Table missing: {e}')

# ── Gold table schema ─────────────────────────────────────────────────────
print('\n[2] Gold Table Schema')
required_cols = [
    'claim_id','claimant_id','fraud_risk_score','risk_tier',
    'primary_alert','claim_amount','claim_status','filed_date',
    'recency_bucket','scored_at'
]
try:
    gold_cols = [c.name for c in spark.table('gold_claims_fraud_scored').schema]
    for col in required_cols:
        check(f'Column: {col}', col in gold_cols)
except Exception as e:
    check('Gold schema readable', False, str(e))

# ── Fraud score distribution ───────────────────────────────────────────────
print('\n[3] Fraud Score Distribution')
try:
    stats = spark.sql('''
        SELECT
            MIN(fraud_risk_score)  AS min_score,
            MAX(fraud_risk_score)  AS max_score,
            AVG(fraud_risk_score)  AS avg_score,
            COUNT(CASE WHEN risk_tier = 'HIGH'   THEN 1 END) AS high_count,
            COUNT(CASE WHEN risk_tier = 'MEDIUM' THEN 1 END) AS med_count,
            COUNT(*) AS total
        FROM gold_claims_fraud_scored
    ''').collect()[0]
    check('Score range 0–1',       0.0 <= stats.min_score and stats.max_score <= 1.0,
          f'min={stats.min_score:.3f} max={stats.max_score:.3f}')
    check('HIGH tier >= 5% of claims', stats.high_count / stats.total >= 0.05,
          f'{stats.high_count}/{stats.total} ({100*stats.high_count/stats.total:.1f}%)')
    check('MEDIUM tier populated',     stats.med_count > 0, f'{stats.med_count} claims')
except Exception as e:
    check('Score distribution', False, str(e))

# ── NULL checks on key columns ────────────────────────────────────────────
print('\n[4] NULL Checks on Key Columns')
null_cols = ['claim_id','fraud_risk_score','risk_tier','primary_alert','claim_status']
try:
    for col in null_cols:
        nulls = spark.sql(f'SELECT COUNT(*) AS n FROM gold_claims_fraud_scored WHERE {col} IS NULL').collect()[0].n
        check(f'No NULLs in {col}', nulls == 0, f'{nulls} NULLs found')
except Exception as e:
    check('NULL checks', False, str(e))

# ── Velocity feature ──────────────────────────────────────────────────────
print('\n[5] Velocity Feature')
try:
    vel = spark.sql('SELECT MAX(claim_velocity_24mo) AS mx FROM gold_claims_fraud_scored').collect()[0].mx
    check('Velocity > 1 exists (window working)', vel > 1, f'max velocity = {vel}')
except Exception as e:
    check('Velocity feature', False, str(e))

# ── Final ──────────────────────────────────────────────────────────────────
print('\n' + '=' * 55)
if issues:
    print(f'⚠️  {len(issues)} check(s) FAILED:')
    for i in issues: print(f'    • {i}')
    print('   See DEPLOYMENT.md#troubleshooting')
else:
    print('✅  ALL CHECKS PASSED — Demo ready!')
    print('   Next: Set up Fabric Data Agent (DEPLOYMENT.md Phase 4)')
print('=' * 55)
