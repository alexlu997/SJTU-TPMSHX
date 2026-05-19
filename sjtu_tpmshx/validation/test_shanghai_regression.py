"""
test_shanghai_regression.py — Shanghai 16 case refined 网格回归测试

锁定当前 dP 预测作为回归基线。任何修改 SIMPLE 求解器、网格处理、or K/c_F
代理的改动都应重跑此测试，确保不会意外改变已验证的物理行为。

生成时间：2026-04-17 端到端 refined 网格定版
基线数据：data/shanghai_validation.xlsx
预期 RMSRE：32.33% (全 16 case), 33.08% (Re>600)
预期 max|err_Q|：5.70%

若有大改动导致数值漂移 > 3%，请：
  1. 确认改动符合物理预期
  2. 用新值更新此文件的 REGRESSION_DP 和 REGRESSION_TOL
  3. 更新 vault/reports/2026-04-17-shanghai-dP-error-analysis-CN.md §13
"""
import os, sys, warnings
from pathlib import Path
import numpy as np
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')

_ROOT = Path(__file__).resolve().parents[1]   # .../sjtu_tpmshx
warnings.filterwarnings('ignore')

# Expected dP_sim from 2026-04-17 refined 定版
REGRESSION_DP = [
    948, 3475, 7446, 12528, 25270, 39738, 47589, 53996,
    61714, 69335, 77167, 85969, 95067, 103553, 111408, 118663,
]
# Relative tolerance for regression (3%)
REGRESSION_TOL = 0.03


def _run_validation_subprocess():
    """Run legacy validate_shanghai and read result xlsx.

    Path updated 2026-05-06 (fix #5): validate_shanghai → legacy/. Regression
    target preserved against v1.0.x baseline; new validation entry points
    are validate_shanghai_lumped_dual_nu (论文 baseline, Q 1.71%) and
    validate_shanghai_3d_real (3D, Q 2.29%).
    """
    import subprocess
    env = dict(os.environ)
    result = subprocess.run(
        [sys.executable, '-m', 'validation.legacy.validate_shanghai'],
        cwd=str(_ROOT),
        capture_output=True, text=True, env=env, timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"validate_shanghai failed:\n{result.stderr}")
    xlsx = _ROOT.parent / 'data' / 'shanghai_validation.xlsx'
    if not xlsx.exists():  # rename-proof legacy fallback
        xlsx = Path(r'D:\Postgraduate\Homogenize\SJTU-TPMSHX\data\shanghai_validation.xlsx')
    return pd.read_excel(xlsx, engine='openpyxl')


def main():
    print("=" * 60)
    print("Shanghai Regression Test (refined grid baseline)")
    print("=" * 60)

    df = _run_validation_subprocess()
    dP_sim = df['dP_air_sim'].values
    dP_exp = df['dP_air_exp'].values

    print(f"\nCase | dP_exp    | dP_sim    | baseline  | drift  | status")
    print("-" * 70)
    all_ok = True
    max_drift = 0.0
    for i in range(16):
        case = i + 1
        baseline = REGRESSION_DP[i]
        actual = dP_sim[i]
        drift = (actual - baseline) / baseline
        status = "✓" if abs(drift) < REGRESSION_TOL else "✗"
        if abs(drift) >= REGRESSION_TOL:
            all_ok = False
        max_drift = max(max_drift, abs(drift))
        print(f"{case:4d} | {dP_exp[i]:9.0f} | {actual:9.0f} | {baseline:9d} | {drift*100:+5.2f}% | {status}")

    errs = (dP_sim - dP_exp) / dP_exp * 100
    rmsre_all = np.sqrt(np.mean(errs**2))
    rmsre_hi = np.sqrt(np.mean(errs[1:]**2))
    Q_errs = df['err_Q%'].values
    max_Q = np.max(np.abs(Q_errs))

    print(f"\nMax dP drift vs baseline: {max_drift*100:.2f}% (tol {REGRESSION_TOL*100:.1f}%)")
    print(f"RMSRE_dP 全 16: {rmsre_all:.2f}% (基线 32.33%)")
    print(f"RMSRE_dP Re>600: {rmsre_hi:.2f}% (基线 33.08%)")
    print(f"max|err_Q|: {max_Q:.2f}% (基线 5.70%)")

    if all_ok:
        print("\n✓ 回归测试通过：所有 case dP 与基线吻合")
    else:
        print("\n✗ 回归失败：存在超容差的 case")
        sys.exit(1)


if __name__ == '__main__':
    main()
