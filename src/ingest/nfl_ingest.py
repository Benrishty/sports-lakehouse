# Databricks notebook source
# MAGIC %md
# MAGIC # NFL ingest: landing → bronze
# MAGIC
# MAGIC Two decoupled steps, so either one can be re-run safely:
# MAGIC
# MAGIC 1. **Land**: download nflverse files into a Unity Catalog Volume as immutable snapshots
# MAGIC    (`/Volumes/<catalog>/<schema>/landing/nfl/<dataset>/snapshot=<UTC timestamp>/<file>`).
# MAGIC    nflverse re-publishes the *whole* current-season file every night, so each run lands a new
# MAGIC    snapshot instead of overwriting one. If Free Edition's outbound allow-list blocks GitHub,
# MAGIC    this step fails soft and you land files with `scripts/land_files.sh` instead.
# MAGIC 2. **Load**: append every landed file that is not in bronze yet to a bronze Delta table, under a
# MAGIC    type contract (see `apply_bronze_contract`). Bronze is append-only, so a file is never loaded twice.
# MAGIC
# MAGIC Dedup of the repeated snapshots happens downstream in the pipeline (AUTO CDC → `silver_*`).

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nfl")
# "current" = the in-progress season only; "backfill" = 1999 → current; or a list like "2023,2024"
dbutils.widgets.text("seasons", "current")
dbutils.widgets.dropdown("download", "true", ["true", "false"])

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
SEASONS_ARG = dbutils.widgets.get("seasons").strip().lower()
DOWNLOAD = dbutils.widgets.get("download") == "true"

LANDING = f"/Volumes/{CATALOG}/{SCHEMA}/landing/nfl"
NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"

# dataset -> (url template, file name template, bronze table)
DATASETS = {
    "pbp": (NFLVERSE + "/pbp/play_by_play_{season}.parquet", "play_by_play_{season}.parquet", "bronze_pbp"),
    "games": (NFLVERSE + "/schedules/games.parquet", "games.parquet", "bronze_games"),
}

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.landing")

# COMMAND ----------

import datetime as dt
import os
import re
import shutil
import tempfile
import urllib.request

from pyspark.sql import DataFrame, functions as F, types as T

FIRST_SEASON = 1999  # first season nflverse publishes with EPA


def current_nfl_season(today: dt.date) -> int:
    """NFL seasons are labelled by the year they start; Jan/Feb playoff games belong to the prior year."""
    return today.year if today.month >= 9 else today.year - 1


def resolve_seasons(arg: str, today: dt.date) -> list[int]:
    current = current_nfl_season(today)
    if arg == "current":
        return [current]
    if arg == "backfill":
        return list(range(FIRST_SEASON, current + 1))
    return sorted({int(s) for s in re.split(r"[,\s]+", arg) if s})


def landed_files(dataset: str) -> list[str]:
    """Every file under landing/nfl/<dataset>/snapshot=*/ ."""
    root = f"{LANDING}/{dataset}"
    if not os.path.exists(root):
        return []
    return sorted(
        os.path.join(root, snap, name)
        for snap in os.listdir(root)
        if snap.startswith("snapshot=")
        for name in os.listdir(os.path.join(root, snap))
    )


def download(url: str, dest: str) -> None:
    """Stream to a local temp file first, then copy into the Volume, so a half-download never lands."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        with urllib.request.urlopen(url, timeout=120) as resp:
            shutil.copyfileobj(resp, tmp)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy(tmp.name, dest)
    os.remove(tmp.name)

# COMMAND ----------

# MAGIC %md ## 1. Land

# COMMAND ----------

today = dt.datetime.now(dt.timezone.utc)
snapshot = today.strftime("%Y%m%dT%H%M%SZ")
seasons = resolve_seasons(SEASONS_ARG, today.date())
current = current_nfl_season(today.date())
print(f"seasons={seasons[0]}..{seasons[-1]} ({len(seasons)})  snapshot={snapshot}")

download_failures = []
if DOWNLOAD:
    already = {os.path.basename(p) for p in landed_files("pbp")}
    targets = []
    for season in seasons:
        url_t, name_t, _ = DATASETS["pbp"]
        name = name_t.format(season=season)
        # Finished seasons rarely change: land them once. The current season is re-landed every run.
        if season != current and name in already:
            continue
        targets.append((url_t.format(season=season), f"{LANDING}/pbp/snapshot={snapshot}/{name}"))
    targets.append((DATASETS["games"][0], f"{LANDING}/games/snapshot={snapshot}/{DATASETS['games'][1]}"))

    for url, dest in targets:
        try:
            download(url, dest)
            print(f"landed {dest}")
        except Exception as e:  # noqa: BLE001 - report every failure, load whatever did land
            download_failures.append((url, repr(e)))
            print(f"FAILED {url}: {e!r}")

if download_failures:
    print(
        "\nSome downloads failed. On Databricks Free Edition this usually means github.com is not on the "
        "outbound allow-list. Land the files from your laptop instead (see scripts/land_files.sh), then "
        "re-run this notebook with download=false.\n"
    )

# COMMAND ----------

# MAGIC %md ## 2. Load (landing → bronze)

# COMMAND ----------


def apply_bronze_contract(df: DataFrame) -> DataFrame:
    """Bronze type contract.

    nflverse column types drift between seasons (e.g. `goal_to_go` is INT in 2010 and DOUBLE in
    every other season), which breaks appends into one table. Bronze therefore stores every numeric
    column as DOUBLE and every all-null column as STRING. Real types are applied in silver.
    """
    cols = []
    for f in df.schema.fields:
        if isinstance(f.dataType, T.NumericType):
            cols.append(F.col(f"`{f.name}`").cast("double").alias(f.name))
        elif isinstance(f.dataType, T.NullType):
            cols.append(F.col(f"`{f.name}`").cast("string").alias(f.name))
        else:
            cols.append(F.col(f"`{f.name}`"))
    return df.select(cols)


def snapshot_ts(path: str) -> dt.datetime:
    stamp = re.search(r"snapshot=(\d{8}T\d{6}Z)", path).group(1)
    return dt.datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")


def load_new_files(dataset: str) -> int:
    table = f"{CATALOG}.{SCHEMA}.{DATASETS[dataset][2]}"
    loaded = set()
    if spark.catalog.tableExists(table):
        loaded = {r[0] for r in spark.table(table).select("_source_file").distinct().collect()}

    new = [p for p in landed_files(dataset) if p not in loaded]
    for path in new:
        df = (
            apply_bronze_contract(spark.read.parquet(path))
            .withColumn("_source_file", F.lit(path))
            .withColumn("_snapshot_ts", F.lit(snapshot_ts(path)).cast("timestamp"))
            .withColumn("_ingested_at", F.current_timestamp())
        )
        (df.write.mode("append").option("mergeSchema", "true").saveAsTable(table))
        print(f"{table} += {path}")
    return len(new)


loaded_counts = {ds: load_new_files(ds) for ds in DATASETS}
print(loaded_counts)

# COMMAND ----------

# Fail the job (so the pipeline task does not run on stale data) only if nothing usable happened.
if download_failures and sum(loaded_counts.values()) == 0:
    raise RuntimeError(f"No new data: {len(download_failures)} downloads failed and nothing new was landed.")
