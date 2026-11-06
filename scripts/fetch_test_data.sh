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
ls -la "$OUT"
