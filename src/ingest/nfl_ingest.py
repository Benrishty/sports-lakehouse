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

# dataset -> (url template, file name template, bronze table, first season)
# Seasonal datasets (first season set) publish one file per season; the current season is re-landed every run.
# Whole-file datasets (first season None) are one file covering all seasons and are re-landed every run.
DATASETS = {
    # play-level and box scores
    "pbp": (NFLVERSE + "/pbp/play_by_play_{season}.parquet", "play_by_play_{season}.parquet", "bronze_pbp", 1999),
    "player_week": (NFLVERSE + "/stats_player/stats_player_week_{season}.parquet", "stats_player_week_{season}.parquet",
                    "bronze_player_week", 1999),
    "snap_counts": (NFLVERSE + "/snap_counts/snap_counts_{season}.parquet", "snap_counts_{season}.parquet", "bronze_snap_counts", 2012),
    "injuries": (NFLVERSE + "/injuries/injuries_{season}.parquet", "injuries_{season}.parquet", "bronze_injuries", 2009),
    "ftn_charting": (NFLVERSE + "/ftn_charting/ftn_charting_{season}.parquet", "ftn_charting_{season}.parquet", "bronze_ftn_charting", 2022),
    # weekly roster status: ACT / RES (injured reserve, PUP, NFI) / INA / DEV (practice squad). The weekly injury
    # report drops players once they go on IR, so this is the source of truth for availability.
    "roster_week": (NFLVERSE + "/weekly_rosters/roster_weekly_{season}.parquet", "roster_weekly_{season}.parquet", "bronze_roster_week", 2002),
    # schedules and dimensions
    "games": (NFLVERSE + "/schedules/games.parquet", "games.parquet", "bronze_games", None),
    "teams": (NFLVERSE + "/teams/teams_colors_logos.parquet", "teams_colors_logos.parquet", "bronze_teams", None),
    "players": (NFLVERSE + "/players/players.parquet", "players.parquet", "bronze_players", None),
    # front office: contracts (OverTheCap), draft, combine
    "contracts": (NFLVERSE + "/contracts/historical_contracts.parquet", "historical_contracts.parquet", "bronze_contracts", None),
    "draft_picks": (NFLVERSE + "/draft_picks/draft_picks.parquet", "draft_picks.parquet", "bronze_draft_picks", None),
    "combine": (NFLVERSE + "/combine/combine.parquet", "combine.parquet", "bronze_combine", None),
    # advanced player stats: Next Gen Stats (2016+) and Pro Football Reference (2018+)
    "ngs_passing": (NFLVERSE + "/nextgen_stats/ngs_passing.parquet", "ngs_passing.parquet", "bronze_ngs_passing", None),
    "ngs_rushing": (NFLVERSE + "/nextgen_stats/ngs_rushing.parquet", "ngs_rushing.parquet", "bronze_ngs_rushing", None),
    "ngs_receiving": (NFLVERSE + "/nextgen_stats/ngs_receiving.parquet", "ngs_receiving.parquet", "bronze_ngs_receiving", None),
    "pfr_def": (NFLVERSE + "/pfr_advstats/advstats_season_def.parquet", "advstats_season_def.parquet", "bronze_pfr_def", None),
    "pfr_pass": (NFLVERSE + "/pfr_advstats/advstats_season_pass.parquet", "advstats_season_pass.parquet", "bronze_pfr_pass", None),
    "pfr_rush": (NFLVERSE + "/pfr_advstats/advstats_season_rush.parquet", "advstats_season_rush.parquet", "bronze_pfr_rush", None),
    "pfr_rec": (NFLVERSE + "/pfr_advstats/advstats_season_rec.parquet", "advstats_season_rec.parquet", "bronze_pfr_rec", None),
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
    targets = []
    for ds, (url_t, name_t, _, first_season) in DATASETS.items():
        if first_season is None:
            targets.append((url_t, f"{LANDING}/{ds}/snapshot={snapshot}/{name_t}"))
            continue
        already = {os.path.basename(p) for p in landed_files(ds)}
        for season in (x for x in seasons if x >= first_season):
            name = name_t.format(season=season)
            # Finished seasons rarely change: land them once. The current season is re-landed every run.
            if season != current and name in already:
                continue
            targets.append((url_t.format(season=season), f"{LANDING}/{ds}/snapshot={snapshot}/{name}"))

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
    column as DOUBLE, every all-null column as STRING, and nested columns (structs, arrays, maps, e.g. the
    contract history in the OverTheCap file) as JSON text. Real types are applied in silver.
    """
    cols = []
    for f in df.schema.fields:
        if isinstance(f.dataType, (T.StructType, T.ArrayType, T.MapType)):
            cols.append(F.to_json(F.col(f"`{f.name}`")).alias(f.name))
        elif isinstance(f.dataType, T.NumericType):
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
