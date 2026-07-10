#!/usr/bin/env bash
# port_retest_pull.sh — 从 pyfluent 服务器拉回端口复测结果 (本地执行).
#
# 用法:  bash scripts/port_retest_pull.sh <user>@<server>
# 可选:  PORT_WORKDIR=~/tpmshx-port (与服务器脚本一致时不用改)

set -euo pipefail
HOST="${1:?用法: bash scripts/port_retest_pull.sh <user>@<server>}"
REMOTE="${PORT_WORKDIR:-~/tpmshx-port}/SJTU-TPMSHX/reports/port_dim_retest"

mkdir -p reports
scp -r "$HOST:$REMOTE" reports/
echo "== 四臂判决 =="
for j in reports/port_dim_retest/*/port_metrics.json; do
    python - "$j" <<'EOF'
import json, sys
m = json.load(open(sys.argv[1]))
print(f"{sys.argv[1].split('/')[-2]:>16}: D={m['decision_dim']:>2}  "
      f"HV gain {m['hv_gain_pct']:+6.2f}%  dominated {m['uniform_dominated_frac']*100:3.0f}%  "
      f"({m['budget']['graded']} evals, {m['wall_seconds']/3600:.1f} h)")
EOF
done
