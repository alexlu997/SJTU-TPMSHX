"""UI provenance follows the source checkout, including linked worktrees."""
import subprocess
import os

import pytest

from sjtu_tpmshx import main
from sjtu_tpmshx.ui.mixins import io_actions, run_history


@pytest.mark.parametrize('override', [None, 'GIT_DIR', 'GIT_COMMON_DIR', 'GIT_WORK_TREE'])
def test_source_checkout_worktree_and_no_metadata(tmp_path, monkeypatch, override):
    def git(root, *args):
        return subprocess.check_output(
            ['git', '-C', str(root), *args], text=True,
            stderr=subprocess.DEVNULL,
        ).strip()

    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init')
    git(repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
        '-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-m', 'first')
    expected = git(repo, 'rev-parse', 'HEAD')[:7]
    worktree = tmp_path / 'worktree'
    git(repo, 'worktree', 'add', '--detach', str(worktree), 'HEAD')
    git(repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
        '-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-m', 'second')
    checkout_commit = git(repo, 'rev-parse', 'HEAD')[:7]
    foreign = tmp_path / 'foreign'
    git(repo, 'clone', str(repo), str(foreign))
    git(foreign, '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
        '-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-m', 'foreign')
    if override:
        target = {'GIT_DIR': foreign / '.git',
                  'GIT_COMMON_DIR': foreign / 'missing-metadata',
                  'GIT_WORK_TREE': foreign}[override]
        monkeypatch.setenv(override, str(target))
    inherited = os.environ.copy()
    monkeypatch.chdir(repo)  # Different commit from the running worktree.
    assert (worktree / '.git').is_file()
    for root, commit in ((worktree, expected),
                         (repo, checkout_commit)):
        monkeypatch.setattr(main, '__file__', str(root / 'sjtu_tpmshx' / 'main.py'))
        assert main._git_commit_hash() == commit
        assert io_actions._git_commit_hash() == commit
        assert run_history._git_commit_hash() == commit

    # An installed/frozen layout inside another repo must not inherit its HEAD.
    monkeypatch.setattr(main, '__file__', str(repo / 'installed' / 'sjtu_tpmshx' / 'main.py'))
    assert main._git_commit_hash() == ''
    assert os.environ == inherited


def test_git_unavailable_or_invalid_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(main, '__file__', str(tmp_path / 'sjtu_tpmshx' / 'main.py'))
    (tmp_path / '.git').mkdir()
    assert main._git_commit_hash() == ''
    monkeypatch.setenv('PATH', '')
    assert main._git_commit_hash() == ''
