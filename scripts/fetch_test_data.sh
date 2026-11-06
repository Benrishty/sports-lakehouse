#!/usr/bin/env bash
# Download the sample nflverse files tests/local_e2e.py runs against.
set -euo pipefail
OUT="${1:-tests/data}"
BASE="https://github.com/nflverse/nflverse-data/releases/download"
mkdir -p "$OUT"
for y in 1999 2010 2020 2025 2026; do
  curl -fsSL -o "$OUT/play_by_play_$y.parquet" "$BASE/pbp/play_by_play_$y.parquet"
done
curl -fsSL -o "$OUT/games.parquet" "$BASE/schedules/games.parquet"
for y in 1999 2026; do
  curl -fsSL -o "$OUT/stats_player_week_$y.parquet" "$BASE/stats_player/stats_player_week_$y.parquet"
done
curl -fsSL -o "$OUT/teams_colors_logos.parquet" "$BASE/teams/teams_colors_logos.parquet"
curl -fsSL -o "$OUT/players.parquet" "$BASE/players/players.parquet"
# front-office / advanced samples
for f in snap_counts/snap_counts_2015 snap_counts/snap_counts_2026 injuries/injuries_2012 injuries/injuries_2026 \
         ftn_charting/ftn_charting_2022 ftn_charting/ftn_charting_2026 contracts/historical_contracts \
         draft_picks/draft_picks combine/combine nextgen_stats/ngs_passing nextgen_stats/ngs_rushing \
         nextgen_stats/ngs_receiving pfr_advstats/advstats_season_def pfr_advstats/advstats_season_pass \
         pfr_advstats/advstats_season_rush pfr_advstats/advstats_season_rec; do
  curl -fsSL -o "$OUT/$(basename "$f").parquet" "$BASE/$f.parquet"
done
ls -la "$OUT"
