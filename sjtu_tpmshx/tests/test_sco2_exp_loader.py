from pathlib import Path

import pytest

from sjtu_tpmshx.validation.sco2_exp.load_sco2_exp import load_exp


_XLSX = Path(__file__).resolve().parents[2] / "data/raw_data/sCO2-Experient.xlsx"


@pytest.mark.skipif(not _XLSX.exists(),
                    reason="sCO2 experiment Excel not on this machine")
def test_diamond_redo_cases_are_rejected():
    experiment = load_exp("Diamond")
    redo = experiment[experiment["case"].isin([25, 42])]

    assert set(redo["done"]) == {"重做"}
    assert len(redo) == 4
    assert not redo["ok_done"].any()
