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

land() {  # land <release path> <dataset dir>
  local f; f="$(basename "$1")"
  echo "→ $f"
  curl -fsSL -o "$TMP/$f" "$BASE/$1"
  databricks fs cp "$TMP/$f" "$VOL/$2/snapshot=${SNAP}/$f"
}

for season in $(seq "$FIRST" "$LAST"); do
  land "pbp/play_by_play_${season}.parquet" pbp
  land "stats_player/stats_player_week_${season}.parquet" player_week
  [ "$season" -ge 2012 ] && land "snap_counts/snap_counts_${season}.parquet" snap_counts
  [ "$season" -ge 2009 ] && land "injuries/injuries_${season}.parquet" injuries
  [ "$season" -ge 2022 ] && land "ftn_charting/ftn_charting_${season}.parquet" ftn_charting
done
land schedules/games.parquet games
land teams/teams_colors_logos.parquet teams
land players/players.parquet players
land contracts/historical_contracts.parquet contracts
land draft_picks/draft_picks.parquet draft_picks
land combine/combine.parquet combine
for k in passing rushing receiving; do land "nextgen_stats/ngs_${k}.parquet" "ngs_${k}"; done
for k in def pass rush rec; do land "pfr_advstats/advstats_season_${k}.parquet" "pfr_${k}"; done

echo "Landed snapshot ${SNAP}. Now run the nfl_ingest notebook with download=false."
