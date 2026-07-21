import openpyxl
from sjtu_tpmshx.design.cli import run

def _spec(path):
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["case","hot_fluid","T_in_h_K","P_in_h_kPa","mdot_h",
               "cold_fluid","T_in_c_K","P_in_c_kPa","mdot_c","Q_kW","dPlim_h","dPlim_c"])
    ws.append([1,"air",688.23,1088.7,0.2855,"water",320.0,200.0,0.5,30.0,0.075,0.05])
    wb.save(path)

def test_run_fixed_mode(tmp_path):
    f = tmp_path / "spec.xlsx"; _spec(f); out = tmp_path / "out.xlsx"
    rc = run(["--xlsx", str(f), "--mode", "fixed",
              "--cell", "Diamond,7,0.5", "--out", str(out)])
    assert rc == 0 and out.exists()

def test_run_auto_mode_small_grid(tmp_path):
    f = tmp_path / "spec.xlsx"; _spec(f); out = tmp_path / "out.xlsx"
    rc = run(["--xlsx", str(f), "--mode", "auto",
              "--nodes", "Diamond:6,7:0.5", "--out", str(out)])
    assert rc == 0
