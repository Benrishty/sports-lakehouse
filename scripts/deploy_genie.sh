#!/usr/bin/env bash
# Create the NFL Genie space, or update it in place if genie/space_id exists.
#   python scripts/build_genie_space.py && ./scripts/deploy_genie.sh
# Needs the Databricks CLI, logged in. WAREHOUSE (name) and PARENT (workspace folder) can be overridden.
set -euo pipefail
cd "$(dirname "$0")/.."
WAREHOUSE="${WAREHOUSE:-Serverless Starter Warehouse}"
SPACE_JSON="$(python3 -c 'import json;print(json.dumps(json.load(open("genie/nfl_genie_space.json")),separators=(",",":")))')"
TITLE="NFL Efficiency Genie"
DESC="Ask questions about NFL team and quarterback efficiency (EPA), records and results against the spread, 1999 to this week."

if [[ -f genie/space_id ]]; then
  databricks genie update-space "$(cat genie/space_id)" --serialized-space "$SPACE_JSON" --title "$TITLE" --description "$DESC" -o json >/dev/null
  echo "updated space $(cat genie/space_id)"
else
  WH_ID="$(databricks warehouses list -o json | python3 -c "import sys,json;print([w['id'] for w in json.load(sys.stdin) if w['name']==sys.argv[1]][0])" "$WAREHOUSE")"
  PARENT="${PARENT:-/Workspace/Users/$(databricks current-user me -o json | python3 -c 'import sys,json;print(json.load(sys.stdin)["userName"])')}"
  databricks genie create-space "$WH_ID" "$SPACE_JSON" --title "$TITLE" --description "$DESC" --parent-path "$PARENT" -o json \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["space_id"])' > genie/space_id
  echo "created space $(cat genie/space_id)"
fi
