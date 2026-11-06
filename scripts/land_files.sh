#!/usr/bin/env bash
# Fallback lander: download nflverse files on YOUR machine and copy them into the Databricks Volume.
# Use this when the ingest notebook can't reach github.com (Free Edition outbound allow-list).
# Then run the ingest notebook / job with download=false to load them into bronze.
#
#   ./scripts/land_files.sh 2026              # one season (plus the games file)
#   ./scripts/land_files.sh 1999 2026         # a range, e.g. the first backfill
#
# Needs: the Databricks CLI, logged in (`databricks auth login`). CATALOG / SCHEMA env vars override defaults.
set -euo pipefail

CATALOG="${CATALOG:-workspace}"
SCHEMA="${SCHEMA:-nfl}"
FIRST="${1:?usage: land_files.sh <first_season> [last_season]}"
LAST="${2:-$FIRST}"
BASE="https://github.com/nflverse/nflverse-data/releases/download"
SNAP="$(date -u +%Y%m%dT%H%M%SZ)"
VOL="dbfs:/Volumes/${CATALOG}/${SCHEMA}/landing/nfl"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for season in $(seq "$FIRST" "$LAST"); do
  f="play_by_play_${season}.parquet"
  echo "→ $f"
  curl -fsSL -o "$TMP/$f" "$BASE/pbp/$f"
  databricks fs cp "$TMP/$f" "$VOL/pbp/snapshot=${SNAP}/$f"
done

echo "→ games.parquet"
curl -fsSL -o "$TMP/games.parquet" "$BASE/schedules/games.parquet"
databricks fs cp "$TMP/games.parquet" "$VOL/games/snapshot=${SNAP}/games.parquet"

echo "Landed snapshot ${SNAP}. Now run the nfl_ingest notebook with download=false."
