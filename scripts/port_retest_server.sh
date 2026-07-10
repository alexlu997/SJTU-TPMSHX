#!/usr/bin/env bash
# port_retest_server.sh — 在 pyfluent 服务器上并行跑端口维数复测四臂.
#
# 用法 (服务器上, 任意目录):
#   bash port_retest_server.sh            # 首次: clone + venv + 四臂并行
#   bash port_retest_server.sh status     # 查看四臂进度
#
# 前置 (仅一次): 本地把标定数据传上来 (gitignored, clone 不带):
#   scp -r data/raw_data  <user>@<server>:~/tpmshx-port/SJTU-TPMSHX/data/
#
# 四臂: ctrl4/ctrl6 × seed 7/123, SAAS, 无早停. 每臂独立算 45 点均匀扫掠
# (8 min, 避免臂间耦合). 预计墙钟 ~5-8 h (32 维臂 ~3-4 h, 72 维臂 ~5-7 h).

set -euo pipefail

WORKDIR="${PORT_WORKDIR:-$HOME/tpmshx-port}"
REPO="$WORKDIR/SJTU-TPMSHX"
BRANCH="worktree-m0-optimizer-debt"
LOGD="$WORKDIR/logs"
PY="$WORKDIR/venv/bin/python"

if [ "${1:-}" = "status" ]; then
    for f in "$LOGD"/*.log; do
        [ -f "$f" ] || continue
        echo "== $(basename "$f") =="
        grep -E "\[PORT\]|\[qNEHVI\] iter|Traceback" "$f" | tail -3
    done
    exit 0
fi

mkdir -p "$WORKDIR" "$LOGD"

# 1. clone / update
if [ ! -d "$REPO/.git" ]; then
    git clone -b "$BRANCH" https://github.com/alexlu997/SJTU-TPMSHX.git "$REPO"
else
    git -C "$REPO" fetch origin "$BRANCH" && git -C "$REPO" checkout "$BRANCH" \
        && git -C "$REPO" pull --ff-only origin "$BRANCH"
fi

# 2. venv + deps (幂等)
if [ ! -x "$PY" ]; then
    python3 -m venv "$WORKDIR/venv"
    "$WORKDIR/venv/bin/pip" install --upgrade pip
fi
"$WORKDIR/venv/bin/pip" install -q -r "$REPO/requirements.txt"
# 优化器栈额外依赖 (requirements.txt 只列求解器): CPU torch + botorch
"$WORKDIR/venv/bin/pip" install -q torch --index-url https://download.pytorch.org/whl/cpu
"$WORKDIR/venv/bin/pip" install -q botorch gpytorch

# 3. 标定数据在位检查 (worktree-rawdata 陷阱: 缺 raw_data 会静默回退 CSV 标定)
if [ ! -d "$REPO/data/raw_data" ]; then
    echo "FATAL: $REPO/data/raw_data 不存在 (gitignored)."
    echo "本地执行:  scp -r data/raw_data <user>@<server>:$REPO/data/"
    exit 1
fi

# 4. 四臂并行 (每臂 2 线程上限, 防超订)
cd "$REPO"
NCORE=$(nproc)
THREADS=$(( NCORE / 4 )); [ "$THREADS" -lt 1 ] && THREADS=1; [ "$THREADS" -gt 4 ] && THREADS=4
export PYTHONHASHSEED=0
export PYTHONPATH="$REPO/sjtu_tpmshx"
export OMP_NUM_THREADS=$THREADS MKL_NUM_THREADS=$THREADS NUMBA_NUM_THREADS=$THREADS

launch() {  # launch <ctrl> <seed>
    local tag="c${1}s${2}"
    if [ -f "$LOGD/$tag.log" ] && grep -q "\[PORT\] DONE" "$LOGD/$tag.log"; then
        echo "skip $tag (already DONE)"; return
    fi
    nohup "$PY" -u sjtu_tpmshx/runs/run_port_dim_retest.py \
        --ctrl "$1" --seed "$2" --jobs 4 \
        > "$LOGD/$tag.log" 2>&1 &
    echo "launched $tag pid=$!"
}

launch 4 7
launch 4 123
launch 6 7
launch 6 123

echo "四臂已启动. 进度: bash $0 status"
echo "结果目录: $REPO/reports/port_dim_retest/"
