"""Unit tests for validation.harness._provenance.

C.4 of the 2026-05-06 audit fix campaign — every validation CSV now
carries a comment-prefixed provenance header (script + commit + date)
plus a sidecar ``.meta.json``. This test exercises the helper end-to-end
to lock in the contract.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from validation.harness._provenance import (
    write_csv_with_provenance,
    backfill_provenance,
    read_csv_with_provenance,
)


# ---------------------------------------------------------------- write


def test_write_csv_with_provenance_creates_header_and_sidecar(tmp_path):
    df = pd.DataFrame({'a': [1, 2, 3], 'b': [4.0, 5.0, 6.0]})
    out = tmp_path / 'out.csv'
    meta = write_csv_with_provenance(df, out, 'tests/fake.py')

    # Header on first three lines
    lines = out.read_text(encoding='utf-8').splitlines()
    assert lines[0].startswith('# script:')
    assert lines[1].startswith('# commit:')
    assert lines[2].startswith('# date:')
    assert lines[3] == 'a,b'

    # Sidecar present + minimal fields
    sidecar = out.with_suffix(out.suffix + '.meta.json')
    assert sidecar.exists()
    side = json.loads(sidecar.read_text(encoding='utf-8'))
    assert side['script'].endswith('tests/fake.py')
    assert side['rows'] == 3
    assert side['columns'] == ['a', 'b']

    # Returned meta consistent
    assert meta['rows'] == 3
    assert meta['date'] == side['date']


def test_write_csv_pandas_can_still_read_with_comment(tmp_path):
    df = pd.DataFrame({'x': [10, 20]})
    out = tmp_path / 'one_col.csv'
    write_csv_with_provenance(df, out, 'tests/fake.py')
    re = pd.read_csv(out, comment='#')
    assert list(re['x']) == [10, 20]


# ---------------------------------------------------------------- backfill


def test_backfill_prepends_header_to_existing_csv(tmp_path):
    out = tmp_path / 'legacy.csv'
    out.write_text('a,b\n1,2\n3,4\n', encoding='utf-8')
    meta = backfill_provenance(out, 'tests/legacy.py')
    lines = out.read_text(encoding='utf-8').splitlines()
    assert lines[0].startswith('# script:')
    assert lines[3] == 'a,b'
    assert lines[4] == '1,2'

    side = out.with_suffix(out.suffix + '.meta.json')
    assert side.exists()
    side_data = json.loads(side.read_text(encoding='utf-8'))
    assert side_data.get('backfilled') is True


def test_backfill_idempotent_does_not_double_header(tmp_path):
    out = tmp_path / 'twice.csv'
    out.write_text('a\n1\n', encoding='utf-8')
    backfill_provenance(out, 'tests/twice.py')
    backfill_provenance(out, 'tests/twice.py')
    lines = out.read_text(encoding='utf-8').splitlines()
    # Exactly 3 comment lines (not 6) and 1 column header + 1 row.
    n_comment = sum(1 for ln in lines if ln.startswith('#'))
    assert n_comment == 3, f"expected 3 # lines, found {n_comment}"


# ---------------------------------------------------------------- read


def test_read_csv_with_provenance_returns_df_and_meta(tmp_path):
    out = tmp_path / 'rt.csv'
    df = pd.DataFrame({'x': [1, 2]})
    write_csv_with_provenance(df, out, 'tests/round.py')
    df2, meta = read_csv_with_provenance(out)
    assert list(df2['x']) == [1, 2]
    assert meta['script'].endswith('tests/round.py')


def test_read_csv_with_provenance_falls_back_to_inline_when_no_sidecar(tmp_path):
    out = tmp_path / 'no_side.csv'
    df = pd.DataFrame({'x': [1]})
    write_csv_with_provenance(df, out, 'tests/no_side.py')
    # Drop the sidecar; reader should still get a meta dict.
    out.with_suffix(out.suffix + '.meta.json').unlink()
    _, meta = read_csv_with_provenance(out)
    assert 'script' in meta or 'commit' in meta
