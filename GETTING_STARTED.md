# Getting started: Databricks for someone who already knows Fabric and MotherDuck

This is the walkthrough for Ben. `README.md` is the recruiter-facing page.

## 0. The translation table

Most of Databricks is something you already use under a different name. Fabric is the closest
analogue, since both run Spark notebooks over Delta tables.

| You know (Fabric / MotherDuck / Dagster) | Databricks | Notes |
|---|---|---|
| Workspace | Workspace | Free Edition gives you exactly one. |
| Lakehouse / Warehouse item, MotherDuck database | **Unity Catalog** `catalog.schema.table` | Three-level namespace. Free Edition comes with a catalog called `workspace`. |
| Lakehouse **Files** section, OneLake folders | **Volume** (`/Volumes/catalog/schema/volume/...`) | Governed file storage. Raw parquet lands here. |
| Delta tables | Delta tables | Same format. Liquid clustering (`CLUSTER BY`) replaces partitioning. |
| Fabric notebook (Spark) | Notebook on **serverless** compute | No cluster to configure: attach and run. Python + SQL only on Free Edition. |
| Data Factory pipeline, Dagster job | **Lakeflow Jobs** | Tasks, dependencies, schedules, retries. |
| dbt models, materialized lake views, Dagster assets | **Lakeflow Spark Declarative Pipelines** (formerly DLT) | You declare tables; the engine works out order and incrementality. Closest to Dagster software-defined assets. |
| Data quality checks (Dagster asset checks) | Pipeline **expectations** | `@dp.expect_or_drop(...)` |
| Merge / upsert code | `AUTO CDC` | A declarative MERGE with out-of-order handling and SCD1/SCD2 built in. |
| SQL analytics endpoint, MotherDuck | **SQL warehouse** + SQL editor | Free Edition: one 2X-Small warehouse. |
| Power BI report | **AI/BI dashboard** | Lighter than Power BI, but it lives next to the data. |
| Fabric Data Agent / Copilot | **Genie space** | Natural-language Q&A over tables you choose. |
| Git integration + deployment pipelines | **Git folders** + **Asset Bundles** (`databricks.yml`) | Bundles = infra-as-code for jobs, pipelines and dashboards. |

### Free Edition limits that matter here

- **Serverless only.** No cluster configs (fine, the project is built for it).
- **Outbound internet goes to an allow-list of trusted domains.** Whether github.com is on it decides
  how files get in, so step 2 tests it first.
- One SQL warehouse (2X-Small), 5 concurrent job tasks, one active pipeline per type.
- A daily fair-usage quota. If you exceed it, compute stops until the next day; your data isn't lost.
- Non-commercial use only. A portfolio is fine. Don't use it for client or Bentex work.
- Optional: verifying with LinkedIn raises some limits.

## 1. Clone the repo (2 min)

The project lives at https://github.com/BenRishty/sports-lakehouse (public). On your Mac:

```bash
git clone https://github.com/BenRishty/sports-lakehouse.git ~/code/sports-lakehouse
```

## 2. First hour in the UI: get oriented, test the network (30–45 min)

1. Log in to Free Edition. The left nav has **Workspace** (files and notebooks), **Catalog** (Unity
   Catalog explorer), **Jobs & Pipelines**, **SQL Editor**, **Dashboards** and **Genie**.
2. **Workspace → Create → Git folder**, and paste `https://github.com/BenRishty/sports-lakehouse`.
   The repo is now in the workspace, editable, with commit and push from the UI (like Fabric Git integration).
3. **New → Notebook**, attach to *Serverless*, and run:

   ```python
   import urllib.request
   r = urllib.request.urlopen("https://github.com/nflverse/nflverse-data/releases/download/schedules/games.parquet", timeout=30)
   print(r.status)
   ```

   - **`200`**: GitHub is allowed, and the ingest notebook downloads on its own.
   - **An error or timeout**: it's blocked. Use `scripts/land_files.sh` from your Mac (step 4b) and run the notebook with `download=false`.
4. In **Catalog**, open `workspace`. That's your catalog. The notebook creates the `nfl` schema and
   `landing` volume for you.

## 3. Install the CLI (10 min)

```bash
brew tap databricks/tap
```

```bash
brew install databricks
```

```bash
databricks auth login --host https://<your-workspace-url>
```

The workspace URL is the address bar when you're logged in (`https://dbc-....cloud.databricks.com`).
The login opens a browser and saves a profile.

## 4. Backfill 1999 → today (about 1 hour, mostly waiting)

**a) If GitHub is allowed:** open `src/ingest/nfl_ingest.py` from the Git folder, set the widget
`seasons` = `backfill`, and **Run all**. It lands 28 seasons (~500 MB) and loads `bronze_pbp`.

**b) If GitHub is blocked:** from the repo on your Mac:

```bash
./scripts/land_files.sh 1999 2026
```

Then run the notebook with `seasons=backfill`, `download=false`.

Check in the SQL editor:

```sql
SELECT CAST(season AS INT) AS season, COUNT(*) AS plays
FROM workspace.nfl.bronze_pbp GROUP BY 1 ORDER BY 1;
```

## 5. Deploy the pipeline and job as code (20 min)

From the repo root on your Mac:

```bash
databricks bundle validate
```

```bash
databricks bundle deploy
```

```bash
databricks bundle run nfl_pipeline
```

`deploy` creates `[dev ben] nfl_pipeline` and `[dev ben] nfl_weekly_refresh` in **Jobs & Pipelines**.
Open the pipeline to see the graph (bronze → views → silver → gold), and click a table to see its
expectation pass and fail counts. Take a screenshot for the README.

Then open **Catalog → workspace → nfl → gold_team_season → Lineage**. The column-level lineage graph
is another good screenshot.

When it works, deploy the scheduled version: `databricks bundle deploy -t prod`. Dev mode pauses
schedules; prod runs every Tuesday at 9am ET.

## 6. Dashboard and Genie: the part recruiters actually look at (1–2 hours)

**AI/BI dashboard** (Dashboards → Create). Suggested tiles:

1. Scatter: offensive vs. defensive EPA/play by team, current season (`gold_team_season`), labelled by team.
2. Bar: QB EPA per dropback, current season, top 15 (`gold_qb_season`).
3. Table: "lucky vs. good": wins vs. `net_epa_rank`, and ATS record, by team.
4. Line: one team's net EPA per game across the season (`gold_team_games`), with a team filter.

Then put the dashboard in the repo, so it's code like everything else:

```bash
databricks bundle generate dashboard --existing-path "/Users/<you>/NFL Efficiency.lvdash.json"
```

Commit the generated `resources/*.yml` and `src/*.lvdash.json`.

**Genie space** (Genie → New): add the three gold tables, plus instructions such as *"EPA = expected
points added per play; higher offense is better, lower defense is better. Seasons are labelled by
start year. Regular season unless asked."* Then ask it things like *"Which teams have a winning
record but negative net EPA this year?"* A screen recording of that is a strong portfolio asset,
because it shows the "AI-ready data" story recruiters keep asking you about.

## 7. CI/CD (15 min)

Create a token: Databricks **Settings → Developer → Access tokens**. In the GitHub repo go to
**Settings → Secrets → Actions** and add `DATABRICKS_HOST` and `DATABRICKS_TOKEN`. Every PR
then runs `bundle validate`, and every merge to `main` deploys.

## 8. Make it recruiter-ready

- Add the dashboard screenshot and the pipeline graph to `docs/`, and link them in the README.
- Pin the repo on your GitHub profile.
- One résumé Projects line (draft it into `Resumes/MASTER.md` first, as usual). For example:
  *"Built an incremental NFL lakehouse on Databricks (Unity Catalog, Lakeflow declarative pipelines,
  AUTO CDC, Asset Bundles + GitHub Actions) over 1.3M plays (1999–present), with weekly refresh,
  data-quality expectations and an AI/BI + Genie analytics layer."* Check the play count from your
  bronze query before you use the number.

## Roadmap: the portfolio after this one

| # | Project | New skill it proves | Data |
|---|---|---|---|
| 1 | **NFL lakehouse** (this) | Medallion, CDC, declarative pipelines, DABs, CI/CD | nflverse |
| 2 | **NBA module** on the same framework | Reuse/parameterisation, **SCD2** (player ↔ team history across trades via `stored_as_scd_type=2`), shot-chart modelling | [hoopR-nba-data](https://github.com/sportsdataverse/hoopR-nba-data) parquet, e.g. `nba/player_box/parquet/player_box_2026.parquet`, `nba/shots/...`, `nba/rosters/...` (raw.githubusercontent.com paths; season label = end year) |
| 3 | **Beat the spread?** | ML on the lakehouse: feature tables from rolling EPA, MLflow tracking, honest backtest vs. the closing line | `gold_team_games` |

Do 1 properly before starting 2. One finished project with a dashboard, tests and CI is worth more
than three half-built ones.
