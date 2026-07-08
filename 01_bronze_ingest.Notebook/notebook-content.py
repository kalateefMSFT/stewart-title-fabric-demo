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

# # 01 — Bronze Ingest
# **Purpose:** Generate synthetic claims data and write Bronze Delta tables to the Lakehouse.
# 
# **In production:** Replace the synthetic generation block with:
# - Fabric Mirroring from your claims SQL Server, OR
# - An ADF pipeline landing CSVs/Parquet into `Files/landing/`, then read with `spark.read`
# 
# **Output tables:** `bronze_claims_raw`, `bronze_claimants`, `bronze_properties`

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

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# ── Imports ───────────────────────────────────────────────────────────────
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random

spark = SparkSession.builder.getOrCreate()
spark.conf.set('spark.sql.shuffle.partitions', '8')

SEED = 42
random.seed(SEED)
np.random.seed(SEED)

# ── Config (matches config/settings.env) ──────────────────────────────────
LAKEHOUSE_NAME = 'stewart_title_claims'
NUM_CLAIMS     = 1_200
NUM_CLAIMANTS  = 400
NUM_PROPERTIES = 800

print('✅ Spark', spark.version, '— Bronze ingest starting')

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# ── Generate synthetic data ───────────────────────────────────────────────
# REPLACE THIS BLOCK IN PRODUCTION with Fabric Mirroring or spark.read

FRAUD_TYPES  = ['WIRE_FRAUD','ID_MISMATCH','VELOCITY','TITLE_DEFECT','FORGERY','STRAW_BUYER','NONE']
STATES       = ['TX','FL','CA','NY','IL','AZ','GA','NC','OH','PA']
CLAIM_STATUS = ['OPEN','UNDER_REVIEW','PAID','DENIED','ESCALATED']
FIRST_NAMES  = ['James','Maria','Robert','Linda','Michael','Patricia','David','Jennifer','John','Susan']
LAST_NAMES   = ['Smith','Johnson','Williams','Brown','Jones','Garcia','Miller','Davis','Wilson','Taylor']

def rand_date(days_ago_max=730, days_ago_min=0):
    base = datetime.now() - timedelta(days=days_ago_min)
    return (base - timedelta(days=random.randint(0, days_ago_max - days_ago_min))).date()

claimants = [{
    'claimant_id':    f'CLM-ID-{10000 + i}',
    'first_name':     random.choice(FIRST_NAMES),
    'last_name':      random.choice(LAST_NAMES),
    'state':          random.choice(STATES),
    'ssn_last4':      str(random.randint(1000, 9999)),
    'id_verified':    random.random() > 0.15,
    'account_age_days': random.randint(30, 3650)
} for i in range(NUM_CLAIMANTS)]

props = []
for i in range(NUM_PROPERTIES):
    base_val = round(random.uniform(85_000, 1_200_000), -3)
    pct = random.choices(
        [random.uniform(-0.05, 0.12), random.uniform(0.22, 0.65)],
        weights=[8, 2]
    )[0]
    props.append({
        'property_id':        f'PROP-{20000 + i}',
        'state':              random.choice(STATES),
        'county':             random.choice(['Harris','Miami-Dade','Los Angeles','Cook','Maricopa']),
        'value_at_closing':   base_val,
        'current_value':      round(base_val * (1 + pct), -3),
        'value_pct_change':   round(pct * 100, 2),
        'days_since_closing': random.randint(30, 730),
        'has_lien':           random.random() < 0.08
    })

claimants_df = pd.DataFrame(claimants)
props_df     = pd.DataFrame(props)

claims = []
for i in range(NUM_CLAIMS):
    c = claimants_df.iloc[random.randint(0, NUM_CLAIMANTS - 1)]
    p = props_df.iloc[random.randint(0, NUM_PROPERTIES - 1)]
    filed = rand_date(730)
    fraud_type = random.choices(
        FRAUD_TYPES,
        weights=[0.08, 0.07, 0.06, 0.05, 0.04, 0.03, 0.67]
    )[0]
    amt = random.uniform(5_000, 350_000)
    if fraud_type == 'WIRE_FRAUD':   amt *= random.uniform(1.5, 3.0)
    if fraud_type == 'STRAW_BUYER':  amt *= random.uniform(2.0, 4.0)

    claims.append({
        'claim_id':             f'CLM-2024-{7000 + i}',
        'claimant_id':          c['claimant_id'],
        'property_id':          p['property_id'],
        'claim_type':           random.choice(['LIEN','FORGERY','ENCUMBRANCE','WIRE_FRAUD','TITLE_DEFECT','ID_FRAUD']),
        'fraud_label':          fraud_type,
        'is_confirmed_fraud':   fraud_type != 'NONE',
        'claim_amount':         round(amt, 2),
        'claim_status':         'OPEN' if random.random() < 0.35 else random.choice(CLAIM_STATUS),
        'filed_date':           filed,
        'resolved_date':        (filed + timedelta(days=random.randint(5, 180))) if random.random() > 0.35 else None,
        'assigned_investigator': random.choice(['J.Rivera','K.Thomas','M.Chen','S.Patel','L.Johnson']),
        'state':                c['state'],
        'id_verified':          bool(c['id_verified']),
        'value_pct_change':     float(p['value_pct_change']),
        'has_lien':             bool(p['has_lien']),
        'account_age_days':     int(c['account_age_days'])
    })

claims_df = pd.DataFrame(claims)
print(f'Generated: {len(claimants_df)} claimants | {len(props_df)} properties | {len(claims_df)} claims')
print(f'Fraud distribution:\n{claims_df["fraud_label"].value_counts().to_string()}')

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# ── Write Bronze Delta tables ─────────────────────────────────────────────
for df, name in [
    (claims_df,    'bronze_claims_raw'),
    (claimants_df, 'bronze_claimants'),
    (props_df,     'bronze_properties'),
]:
    (
        spark.createDataFrame(df)
        .write.format('delta')
        .mode('overwrite')
        .option('overwriteSchema', 'true')
        .saveAsTable(name)
    )
    count = spark.table(name).count()
    print(f'✅ {name}: {count:,} rows')

print('\n✅ Bronze ingest complete. Run 02_silver_enrich.ipynb next.')

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
