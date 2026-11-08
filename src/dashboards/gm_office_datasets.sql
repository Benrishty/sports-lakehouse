-- Datasets for the "GM Office" dashboard. Each block starting with an at-sign marker is one dataset.
-- Team-scoped datasets expose a `team` column, which the dashboard-wide Team filter binds to.
-- League-wide datasets call the team `club` on purpose, so the Team filter leaves them unfiltered.
-- Everything is the current season unless the dataset says otherwise.

-- @gm_summary
SELECT st.team, st.team_name, s.team_logo_url,
       CONCAT(st.wins, '-', st.losses, IF(st.ties > 0, CONCAT('-', st.ties), '')) AS record,
       st.division, st.division_rank, st.division_games_back, st.conference_seed, st.in_playoff_position,
       s.net_epa_rank, s.luck_gap, ROUND(s.net_epa_per_play, 3) AS net_epa_per_play,
       CONCAT(b.ats_covers, '-', b.ats_losses) AS ats_record
FROM workspace.nfl.gold_standings st
JOIN workspace.nfl.gold_team_season s ON s.season = st.season AND s.team = st.team
LEFT JOIN workspace.nfl.gold_team_betting b ON b.season = st.season AND b.team = st.team
WHERE st.season = (SELECT MAX(season) FROM workspace.nfl.gold_standings);

-- @gm_report_card
SELECT r.team, r.metric_order, r.phase, r.metric,
       CASE WHEN r.metric LIKE '%rate%' OR r.metric LIKE '%percentage%'
              THEN CONCAT(FORMAT_NUMBER(100 * r.value, 1), '%')
            WHEN r.metric LIKE '%EPA%' THEN FORMAT_NUMBER(r.value, 3)
            ELSE FORMAT_NUMBER(r.value, 1) END AS value,
       CASE WHEN r.metric LIKE '%rate%' OR r.metric LIKE '%percentage%'
              THEN CONCAT(FORMAT_NUMBER(100 * r.league_avg, 1), '%')
            WHEN r.metric LIKE '%EPA%' THEN FORMAT_NUMBER(r.league_avg, 3)
            ELSE FORMAT_NUMBER(r.league_avg, 1) END AS league_avg,
       r.league_rank,
       CASE r.tier WHEN 'top tier' THEN '🟢 top tier' WHEN 'above average' THEN '🟡 above average'
                   WHEN 'below average' THEN '🟠 below average' WHEN 'bottom tier' THEN '🔴 bottom tier'
                   ELSE '⚪ tendency' END AS tier,
       ROUND(100 * r.percentile) AS percentile
FROM workspace.nfl_gm.gold_team_report_card r
WHERE r.season = (SELECT MAX(season) FROM workspace.nfl_gm.gold_team_report_card)
ORDER BY r.metric_order;

-- @gm_percentiles
SELECT r.team, CONCAT(r.phase, ': ', r.metric) AS metric, ROUND(100 * r.percentile) AS percentile
FROM workspace.nfl_gm.gold_team_report_card r
WHERE r.season = (SELECT MAX(season) FROM workspace.nfl_gm.gold_team_report_card) AND r.better <> 'neutral';

-- @gm_freshness
SELECT source, latest_season, latest_week, cadence FROM workspace.nfl_gm.gold_data_freshness;

-- @gm_cap_allocation
SELECT c.team, c.position_group, c.players, ROUND(c.apy_m, 1) AS apy_m,
       ROUND(100 * c.share_of_team_apy, 1) AS team_share_pct,
       ROUND(100 * c.league_avg_share, 1) AS league_avg_pct,
       ROUND(100 * c.top8_avg_share, 1) AS top8_avg_pct,
       ROUND(100 * c.share_vs_league, 1) AS vs_league_pts
FROM workspace.nfl_gm.gold_cap_allocation c
ORDER BY c.share_of_team_apy DESC;

-- @gm_roster_value
SELECT v.team, v.headshot_url, v.player_name, v.position_group, v.age,
       ROUND(v.apy_m, 1) AS apy_m, ROUND(v.guaranteed_m, 1) AS guaranteed_m, v.final_season,
       CONCAT(COALESCE(v.games_played, 0), ' of ', COALESCE(v.team_games_on_roster, 0)) AS games,
       CASE WHEN v.current_roster_status IN ('injured reserve', 'PUP', 'NFI') THEN CONCAT('🩹 ', v.current_roster_status)
            WHEN v.games_missed_injured > 0 THEN CONCAT('missed ', v.games_missed_injured, ' (injury)') ELSE '' END AS availability,
       v.production_metric_name, ROUND(v.production_metric, 2) AS production,
       CASE v.performance_tier WHEN 'elite' THEN '⭐ elite' WHEN 'very good' THEN '🟢 very good'
            WHEN 'average' THEN '🟡 average' WHEN 'below average' THEN '🔴 below average' ELSE '' END AS performance,
       CASE v.contract_verdict WHEN 'bargain' THEN '💰 bargain' WHEN 'overpaid' THEN '⚠️ overpaid'
            WHEN 'fair' THEN 'paid fairly' ELSE '' END AS contract,
       ROUND(100 * v.value_score) AS value_score,
       CASE WHEN v.production_basis LIKE 'last season%' THEN 'last season' WHEN v.production_basis = 'this season' THEN 'this season'
            ELSE 'not scored' END AS judged_on
FROM workspace.nfl_gm.gold_player_value v
WHERE v.team IS NOT NULL
ORDER BY v.apy_m DESC;
-- @gm_expiring
SELECT v.team, v.headshot_url, v.player_name, v.position_group, v.age, ROUND(v.apy_m, 1) AS apy_m,
       v.final_season, v.role, ROUND(100 * v.snap_share) AS snap_pct, ROUND(100 * v.value_score) AS value_score
FROM workspace.nfl_gm.gold_player_value v
WHERE v.team IS NOT NULL AND v.final_season <= v.season
ORDER BY v.snap_share DESC NULLS LAST, v.apy_m DESC;

-- @gm_personnel
SELECT a.latest_team AS team, a.headshot_url, a.player_name, a.position_group, a.role,
       ROUND(100 * a.snap_share) AS snap_pct, a.games,
       ROUND(COALESCE(a.passing_epa, 0) + COALESCE(a.rushing_epa, 0) + COALESCE(a.receiving_epa, 0), 1) AS offensive_epa,
       ROUND(a.rush_yards_over_expected_per_att, 2) AS ryoe_per_att,
       ROUND(a.avg_separation, 2) AS separation_yds,
       ROUND(a.avg_yac_above_expectation, 2) AS yac_over_expected,
       a.sacks_plus_hits,
       ROUND(a.sacks_hits_per_100_snaps, 1) AS sacks_hits_per_100,
       ROUND(a.ball_production_per_100_snaps, 1) AS pd_int_per_100,
       ROUND(a.tackles_per_100_snaps, 1) AS tackles_per_100
FROM workspace.nfl_gm.gold_player_advanced a
WHERE a.season = (SELECT MAX(season) FROM workspace.nfl_gm.gold_player_advanced) AND a.snap_share >= 0.25
ORDER BY CASE a.position_group WHEN 'QB' THEN 1 WHEN 'RB' THEN 2 WHEN 'WR' THEN 3 WHEN 'TE' THEN 4 WHEN 'OL' THEN 5
                               WHEN 'DL' THEN 6 WHEN 'LB' THEN 7 WHEN 'DB' THEN 8 ELSE 9 END, a.snap_share DESC;

-- @gm_draft_projection
SELECT p.projected_pick, t.team_logo_url, p.team AS club, p.team_name,
       CONCAT(p.wins, '-', p.losses, IF(p.ties > 0, CONCAT('-', p.ties), '')) AS record,
       ROUND(p.point_differential) AS point_diff, IF(p.in_playoff_position, 'playoff spot', '') AS status
FROM workspace.nfl_gm.gold_draft_order_projection p
LEFT JOIN workspace.nfl.silver_teams t ON t.team = p.team
ORDER BY p.projected_pick;

-- @gm_draft_classes
SELECT g.team, g.draft_year, g.picks, g.hits, g.pro_bowlers, ROUND(g.surplus_av, 1) AS surplus_av, g.class_rank
FROM workspace.nfl_gm.gold_draft_team_grades g
ORDER BY g.draft_year;

-- @gm_draft_best_misses
SELECT team, kind, headshot_url, draft_year, round, pick, player_name, position, dr_av, expected_av, surplus_av, seasons_started, probowls
FROM (
  SELECT d.team, d.headshot_url, d.draft_year, d.round, d.pick, d.player_name, d.position, d.dr_av,
         ROUND(d.expected_dr_av, 1) AS expected_av, ROUND(d.surplus_av, 1) AS surplus_av, d.seasons_started, d.probowls,
         ROW_NUMBER() OVER (PARTITION BY d.team ORDER BY d.surplus_av DESC) AS best_rk,
         ROW_NUMBER() OVER (PARTITION BY d.team ORDER BY d.surplus_av ASC) AS miss_rk,
         IF(ROW_NUMBER() OVER (PARTITION BY d.team ORDER BY d.surplus_av DESC) <= 10, '✅ best value', '❌ biggest miss') AS kind
  FROM workspace.nfl_gm.gold_draft_pick_value d
  WHERE d.is_mature AND d.draft_year >= (SELECT MAX(draft_year) - 15 FROM workspace.nfl_gm.gold_draft_pick_value) AND d.round <= 3
)
WHERE best_rk <= 10 OR miss_rk <= 10
ORDER BY kind DESC, surplus_av DESC;

-- @gm_position_value
SELECT round, position, picks, ROUND(100 * hit_rate) AS hit_rate_pct, ROUND(100 * pro_bowl_rate) AS pro_bowl_pct,
       ROUND(avg_av_for_team, 1) AS avg_av
FROM workspace.nfl_gm.gold_draft_position_value
WHERE round <= 3 AND picks >= 15
ORDER BY round, hit_rate DESC;

-- @gm_injuries
SELECT i.team, i.headshot_url, i.player_name, i.position, i.status, i.injury, i.role,
       ROUND(100 * i.snap_share) AS snap_pct, i.games_played, i.games_missed_injured, i.last_week_played,
       ROUND(i.apy_m, 1) AS apy_m, i.week
FROM workspace.nfl_gm.gold_injury_report i
ORDER BY CASE WHEN i.status IN ('injured reserve', 'PUP', 'NFI') THEN 1 WHEN i.status = 'Out' THEN 2 WHEN i.status = 'Doubtful' THEN 3
              WHEN i.status = 'Questionable' THEN 4 ELSE 5 END, i.snap_share DESC NULLS LAST;
-- @gm_injury_league
SELECT x.team AS club, x.starter_games_out, x.starters_missing_time, x.player_games_out,
       x.rank_fewest_starter_games_lost
FROM workspace.nfl_gm.gold_team_injury_impact x
WHERE x.season = (SELECT MAX(season) FROM workspace.nfl_gm.gold_team_injury_impact)
ORDER BY x.starter_games_out DESC;

-- ================================================================ Player Profile page
-- Bound to the page's Player picker through player_label. Team columns are named `club` so the
-- dashboard-wide Team filter does not restrict which player you can look up.

-- @pp_header
SELECT f.player_label, f.headshot_url, f.player_name, f.position, f.club, f.jersey_number, f.age, f.height, f.weight_lb,
       f.college, f.years_of_experience, f.draft,
       ROUND(f.apy_m, 1) AS apy_m, ROUND(f.guaranteed_m, 1) AS guaranteed_m, f.final_season,
       CASE f.performance_tier WHEN 'elite' THEN '⭐ elite' WHEN 'very good' THEN '🟢 very good' WHEN 'average' THEN '🟡 average'
            WHEN 'below average' THEN '🔴 below average' ELSE 'not rated' END AS how_good,
       CASE f.contract_verdict WHEN 'bargain' THEN '💰 bargain' WHEN 'overpaid' THEN '⚠️ overpaid' WHEN 'fair' THEN 'paid fairly'
            ELSE '' END AS contract,
       CASE WHEN f.production_basis LIKE 'last season%' THEN 'last season' ELSE f.production_basis END AS judged_on,
       CONCAT(COALESCE(f.games_played, 0), ' of ', COALESCE(f.team_games_on_roster, 0)) AS games_this_season,
       COALESCE(f.current_roster_status, 'not on a roster') AS status, f.latest_injury
FROM workspace.nfl_gm.gold_player_profile f;

-- @pp_percentiles
SELECT f.player_label, p.season,
       CASE p.metric_set WHEN 'DEF' THEN 50 ELSE 0 END + p.metric_order AS metric_order,
       p.metric,
       CASE p.fmt WHEN 'pct' THEN CONCAT(FORMAT_NUMBER(100 * p.value, 1), '%') WHEN 'pct_native' THEN CONCAT(FORMAT_NUMBER(p.value, 1), '%')
                  WHEN 'dec3' THEN FORMAT_NUMBER(p.value, 3) WHEN 'dec2' THEN FORMAT_NUMBER(p.value, 2)
                  WHEN 'int' THEN FORMAT_NUMBER(p.value, 0) ELSE FORMAT_NUMBER(p.value, 1) END AS value,
       ROUND(100 * p.percentile) AS percentile,
       CASE WHEN p.better = 'neutral' THEN '⚪ style (not graded)'
            WHEN p.percentile >= 0.9 THEN '⭐ elite' WHEN p.percentile >= 0.7 THEN '🟢 very good'
            WHEN p.percentile >= 0.4 THEN '🟡 average' ELSE '🔴 below average' END AS grade,
       CASE p.better WHEN 'lower' THEN 'lower is better' WHEN 'higher' THEN 'higher is better' ELSE 'tendency' END AS direction,
       p.peers
FROM workspace.nfl_gm.gold_player_percentiles p
JOIN workspace.nfl_gm.gold_player_profile f ON f.player_id = p.player_id
JOIN (SELECT player_id, MAX(season) AS season FROM workspace.nfl_gm.gold_player_percentiles WHERE qualified GROUP BY player_id) latest
  ON latest.player_id = p.player_id AND latest.season = p.season
WHERE p.qualified
ORDER BY metric_order;

-- @pp_career
SELECT f.player_label, a.season, a.latest_team AS club, a.games, ROUND(100 * a.snap_share) AS snap_pct, a.role,
       a.pass_attempts, a.passing_yards, a.passing_tds, a.interceptions,
       a.carries, a.rushing_yards, a.rushing_tds,
       a.targets, a.receptions, a.receiving_yards, a.receiving_tds,
       ROUND(COALESCE(a.passing_epa, 0) + COALESCE(a.rushing_epa, 0) + COALESCE(a.receiving_epa, 0), 1) AS offensive_epa,
       a.tackles, a.sacks, a.sacks_plus_hits, a.passes_defensed, a.pbp_interceptions AS def_ints,
       ROUND(a.fantasy_points_ppr, 1) AS fantasy_ppr
FROM workspace.nfl_gm.gold_player_advanced a
JOIN workspace.nfl_gm.gold_player_profile f ON f.player_id = a.player_id
ORDER BY a.season DESC;

-- @pp_gamelog
SELECT f.player_label, w.week, w.opponent AS opp, ROUND(100 * GREATEST(COALESCE(s.offense_pct, 0), COALESCE(s.defense_pct, 0))) AS snap_pct,
       w.completions, w.attempts, w.passing_yards, w.passing_tds, w.passing_interceptions AS ints,
       w.carries, w.rushing_yards, w.rushing_tds, w.targets, w.receptions, w.receiving_yards, w.receiving_tds,
       ROUND(COALESCE(w.passing_epa, 0) + COALESCE(w.rushing_epa, 0) + COALESCE(w.receiving_epa, 0), 1) AS offensive_epa,
       w.def_tackles_solo + w.def_tackle_assists AS tackles, w.def_sacks AS sacks, w.def_interceptions AS def_ints,
       ROUND(w.fantasy_points_ppr, 1) AS fantasy_ppr
FROM workspace.nfl.silver_player_week w
JOIN workspace.nfl_gm.gold_player_profile f ON f.player_id = w.player_id
LEFT JOIN workspace.nfl.silver_players pl ON pl.player_id = w.player_id
LEFT JOIN workspace.nfl.silver_snap_counts s ON s.pfr_player_id = pl.pfr_id AND s.season = w.season AND s.week = w.week
WHERE w.season = (SELECT MAX(season) FROM workspace.nfl.silver_player_week) AND w.season_type = 'REG'
ORDER BY w.week;

-- @pp_injuries
SELECT f.player_label, av.season, av.games_played, av.games_missed_injured, av.games_missed_other,
       av.current_roster_status AS season_end_status,
       CONCAT_WS(', ', ARRAY_DISTINCT(COLLECT_LIST(w.injury))) AS injuries_reported
FROM workspace.nfl_gm.gold_player_availability av
JOIN workspace.nfl_gm.gold_player_profile f ON f.player_id = av.player_id
LEFT JOIN workspace.nfl_gm.gold_player_availability_week w ON w.season = av.season AND w.player_id = av.player_id AND w.injury IS NOT NULL
GROUP BY f.player_label, av.season, av.games_played, av.games_missed_injured, av.games_missed_other, av.current_roster_status
ORDER BY av.season DESC;

-- @pp_combine
SELECT f.player_label, c.draft_year AS combine_year, c.position, c.height, c.weight_lb,
       c.forty, c.bench, c.vertical, c.broad_jump, c.cone, c.shuttle
FROM workspace.nfl.silver_combine c
JOIN workspace.nfl.silver_players pl ON pl.pfr_id = c.pfr_player_id
JOIN workspace.nfl_gm.gold_player_profile f ON f.player_id = pl.player_id;
