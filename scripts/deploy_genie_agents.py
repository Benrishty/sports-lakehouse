"""Create or update the GM Genie agents in the workspace.

    python scripts/build_genie_agents.py && python scripts/deploy_genie_agents.py [agent ...]

Creates each space on first run and stores its id in genie/agents/<agent>/space_id; later runs update the
space in place (serialized_space is a full replacement). Needs the Databricks CLI, logged in.
WAREHOUSE overrides the SQL warehouse name.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / "genie/agents"
WAREHOUSE = os.environ.get("WAREHOUSE", "Serverless Starter Warehouse")
CLI = os.environ.get("DATABRICKS_CLI", "databricks")


def cli(*args) -> dict:
    out = subprocess.run([CLI, *args, "-o", "json"], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"databricks {' '.join(args[:2])} failed: {out.stderr.strip()[-500:]}")
    return json.loads(out.stdout or "{}")


def main(selected: list[str]) -> None:
    warehouses = cli("warehouses", "list")
    wh = next(w["id"] for w in warehouses if w["name"] == WAREHOUSE)
    me = cli("current-user", "me")["userName"]
    for d in sorted(p for p in AGENTS_DIR.iterdir() if (p / "space.json").exists()):
        if selected and d.name not in selected:
            continue
        meta = json.loads((d / "meta.json").read_text())
        space = json.dumps(json.loads((d / "space.json").read_text()), separators=(",", ":"))
        id_file = d / "space_id"
        if id_file.exists():
            cli("genie", "update-space", id_file.read_text().strip(), "--serialized-space", space,
                "--title", meta["title"], "--description", meta["description"])
            print(f"updated {meta['title']}: {id_file.read_text().strip()}")
        else:
            r = cli("genie", "create-space", wh, space, "--title", meta["title"], "--description", meta["description"],
                    "--parent-path", f"/Workspace/Users/{me}")
            id_file.write_text(r["space_id"] + "\n")
            print(f"created {meta['title']}: {r['space_id']}")


if __name__ == "__main__":
    main(sys.argv[1:])
