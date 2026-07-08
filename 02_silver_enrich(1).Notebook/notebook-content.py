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

# # 02 — Silver Enrichment
# **Purpose:** Apply feature engineering to Bronze claims data.
# 
# **Key transformations:**
# - Claim velocity window (trailing 24-month count per claimant)
# - Recency bucketing for fast filter queries
# - Property spike flag
# - High-value claim flag
# 
# **Output:** `silver_claims_enriched`

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
from pyspark.sql.window import Window

spark = SparkSession.builder.getOrCreate()
spark.conf.set('spark.sql.shuffle.partitions', '8')
print('✅ Silver enrichment starting')

# CELL ********************

# ── Read Bronze ───────────────────────────────────────────────────────────
claims = spark.table('bronze_claims_raw').withColumn(
    'filed_date', F.to_date(F.col('filed_date'))
)

# ── Claim velocity: count per claimant in trailing 720 days ──────────────
velocity_window = (
    Window.partitionBy('claimant_id')
    .orderBy(F.col('filed_date').cast('long'))
    .rangeBetween(-720 * 86400, 0)
)

silver = (
    claims
    .withColumn('claim_velocity_24mo', F.count('claim_id').over(velocity_window))
    .withColumn('is_high_value',       F.col('claim_amount') > 100_000)
    .withColumn('property_spike',      F.col('value_pct_change') > 20.0)
    .withColumn('days_since_filed',    F.datediff(F.current_date(), F.col('filed_date')))
    .withColumn(
        'recency_bucket',
        F.when(F.col('days_since_filed') <= 30,  'LAST_30D')
         .when(F.col('days_since_filed') <= 90,  'LAST_90D')
         .when(F.col('days_since_filed') <= 365, 'LAST_YEAR')
         .otherwise('OLDER')
    )
)

(
    silver
    .write.format('delta')
    .mode('overwrite')
    .option('overwriteSchema', 'true')
    .saveAsTable('silver_claims_enriched')
)

count = spark.table('silver_claims_enriched').count()
print(f'✅ silver_claims_enriched: {count:,} rows')

# Velocity distribution
silver.groupBy('claim_velocity_24mo').count().orderBy('claim_velocity_24mo').show(10)

print('\n✅ Silver enrichment complete. Run 03_gold_fraud_score.ipynb next.')
