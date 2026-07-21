#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
repo_root=$(CDPATH= cd -- "$script_dir/.." && pwd -P)
project_skill="$repo_root/skills/galaxy-buffett-daily-stock-analysis"
skill_root=${1:-$project_skill}
codex_runtime_root=${CODEX_HOME:-${HOME}/.codex}
quick_validate="$codex_runtime_root/skills/.system/skill-creator/scripts/quick_validate.py"

if [ ! -f "$quick_validate" ]; then
  echo "official quick_validate.py not found: $quick_validate" >&2
  exit 2
fi
if [ ! -d "$skill_root" ]; then
  echo "skill directory not found: $skill_root" >&2
  exit 2
fi

verify_temp_dir=$(mktemp -d "${TMPDIR:-/tmp}/galaxy-buffett-verify.XXXXXX")
cleanup() {
  rm -rf -- "$verify_temp_dir"
}
trap cleanup EXIT HUP INT TERM

python3 -m venv "$verify_temp_dir/venv"
"$verify_temp_dir/venv/bin/python" -m pip install --quiet --disable-pip-version-check "PyYAML==6.0.2"
"$verify_temp_dir/venv/bin/python" "$quick_validate" "$skill_root"

"$verify_temp_dir/venv/bin/python" - "$skill_root/agents/openai.yaml" <<'PY'
from pathlib import Path
import sys
import yaml

path = Path(sys.argv[1])
payload = yaml.safe_load(path.read_text(encoding="utf-8"))
assert isinstance(payload, dict) and isinstance(payload.get("interface"), dict)
interface = payload["interface"]
assert set(interface) == {"display_name", "short_description", "default_prompt"}
assert interface["display_name"] == "Galaxy Buffett - Daily Stock Analysis"
assert "$galaxy-buffett-daily-stock-analysis" in interface["default_prompt"]
print("openai.yaml parsed independently")
PY

set +e
placeholder_output=$(rg -n 'TODO|PLACEHOLDER|example\.com' "$skill_root" 2>&1)
placeholder_status=$?
set -e
if [ "$placeholder_status" -eq 0 ]; then
  echo "$placeholder_output" >&2
  echo "placeholder scan found forbidden text" >&2
  exit 1
fi
if [ "$placeholder_status" -gt 1 ]; then
  echo "$placeholder_output" >&2
  echo "placeholder scan failed with exit $placeholder_status" >&2
  exit "$placeholder_status"
fi
echo "placeholder scan clean (rg exit 1: no matches)"

skill_lines=$(wc -l < "$skill_root/SKILL.md")
if [ "$skill_lines" -ge 500 ]; then
  echo "SKILL.md too large: $skill_lines lines" >&2
  exit 1
fi

PYTHONPYCACHEPREFIX="$verify_temp_dir/pycache" python3 -m py_compile \
  "$skill_root/scripts/read_ibkr_snapshot.py" \
  "$repo_root/scripts/validate_galaxy_buffett_artifacts.py"
python3 "$repo_root/scripts/validate_galaxy_buffett_artifacts.py" skill "$skill_root" "$repo_root"

if [ "$skill_root" = "$project_skill" ]; then
  python3 "$repo_root/scripts/validate_galaxy_buffett_artifacts.py" all "$repo_root"
  git -C "$repo_root" diff --check
fi

echo "GALAXY BUFFETT VERIFICATION PASSED: $skill_root"
