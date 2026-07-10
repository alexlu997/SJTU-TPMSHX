# port_retest_server.ps1 — Windows Server 上并行跑端口维数复测四臂.
#
# 用法 (PowerShell, 任意目录):
#   powershell -ExecutionPolicy Bypass -File port_retest_server.ps1          # 首次: clone + venv + 四臂并行
#   powershell -ExecutionPolicy Bypass -File port_retest_server.ps1 status   # 查看四臂进度
#
# 前置: git + Python 3.11/3.12 在 PATH; gh auth 或 https 凭据可拉私有仓
# (标定数据在私有仓 SJTU-TPMSHX-data, 脚本自动 clone 并拼进 data/raw_data).
#
# 四臂: ctrl4/ctrl6 x seed 7/123, SAAS, 无早停. 64 核机器四臂并行 + 每臂
# jobs=8, 预计墙钟 ~4-7 h.

param([string]$Mode = "run")

$ErrorActionPreference = "Stop"
$WorkDir = if ($env:PORT_WORKDIR) { $env:PORT_WORKDIR } else { Join-Path $HOME "tpmshx-port" }
$Repo    = Join-Path $WorkDir "SJTU-TPMSHX"
$DataRepo = Join-Path $WorkDir "SJTU-TPMSHX-data"
$LogD    = Join-Path $WorkDir "logs"
$Branch  = "master"   # PR #45 合并后; 未合并时改成 worktree-m0-optimizer-debt
$Py      = Join-Path $WorkDir "venv\Scripts\python.exe"

if ($Mode -eq "status") {
    Get-ChildItem "$LogD\*.log" -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "== $($_.Name) =="
        Select-String -Path $_.FullName -Pattern "\[PORT\]|\[qNEHVI\] iter|Traceback" |
            Select-Object -Last 3 | ForEach-Object { Write-Host $_.Line }
    }
    exit 0
}

New-Item -ItemType Directory -Force $WorkDir, $LogD | Out-Null

# 1. clone / update — 主仓 (public) + 数据仓 (private)
if (-not (Test-Path (Join-Path $Repo ".git"))) {
    git clone -b $Branch https://github.com/alexlu997/SJTU-TPMSHX.git $Repo
} else {
    git -C $Repo fetch origin $Branch
    git -C $Repo checkout $Branch
    git -C $Repo pull --ff-only origin $Branch
}
if (-not (Test-Path (Join-Path $DataRepo ".git"))) {
    git clone https://github.com/alexlu997/SJTU-TPMSHX-data.git $DataRepo
} else {
    git -C $DataRepo pull --ff-only
}
# 拼装标定数据 (主仓 data/ 是 gitignored 的; 缺它 DF 代理会静默回退 CSV 标定)
New-Item -ItemType Directory -Force (Join-Path $Repo "data") | Out-Null
Copy-Item -Recurse -Force (Join-Path $DataRepo "raw_data") (Join-Path $Repo "data\")

# 2. venv + deps (幂等)
if (-not (Test-Path $Py)) {
    python -m venv (Join-Path $WorkDir "venv")
    & $Py -m pip install --upgrade pip
}
& $Py -m pip install -q -r (Join-Path $Repo "requirements.txt")
# 优化器栈额外依赖 (requirements.txt 只列求解器): CPU torch + botorch
& $Py -m pip install -q torch --index-url https://download.pytorch.org/whl/cpu
& $Py -m pip install -q botorch gpytorch

# 3. 四臂并行 (64 核: 每臂 8 线程 + joblib 8)
Set-Location $Repo
$env:PYTHONHASHSEED   = "0"
$env:PYTHONPATH       = Join-Path $Repo "sjtu_tpmshx"
$env:OMP_NUM_THREADS  = "8"
$env:MKL_NUM_THREADS  = "8"
$env:NUMBA_NUM_THREADS = "8"

function Launch([int]$Ctrl, [int]$Seed) {
    $tag = "c${Ctrl}s${Seed}"
    $log = Join-Path $LogD "$tag.log"
    if ((Test-Path $log) -and (Select-String -Path $log -Pattern "\[PORT\] DONE" -Quiet)) {
        Write-Host "skip $tag (already DONE)"; return
    }
    $p = Start-Process -FilePath $Py -PassThru -NoNewWindow `
        -ArgumentList "-u", "sjtu_tpmshx/runs/run_port_dim_retest.py",
                      "--ctrl", "$Ctrl", "--seed", "$Seed", "--jobs", "8" `
        -RedirectStandardOutput $log -RedirectStandardError (Join-Path $LogD "$tag.err.log")
    Write-Host "launched $tag pid=$($p.Id)"
}

Launch 4 7
Launch 4 123
Launch 6 7
Launch 6 123

Write-Host "四臂已启动. 进度: powershell -File $PSCommandPath status"
Write-Host "结果目录: $Repo\reports\port_dim_retest\"
