"""Preservation evidence must detect changes without following leaf symlinks."""
import hashlib
from pathlib import Path
import runpy

RECORDER = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/vm/record-baseline.py'))


def test_baseline_hash_changes_when_existing_file_changes(tmp_path):
    path = tmp_path / 'original.desktop'
    path.write_bytes(b'original session')
    before = RECORDER['describe'](path)
    assert before['sha256'] == hashlib.sha256(b'original session').hexdigest()
    assert path.read_bytes() == b'original session'
    path.write_bytes(b'changed session')
    after = RECORDER['describe'](path)
    assert before['sha256'] != after['sha256']


def test_baseline_records_symlink_target_without_reading_destination(tmp_path):
    path = tmp_path / 'display-manager.service'
    path.symlink_to('/nonexistent/gdm.service')
    evidence = RECORDER['describe'](path)
    assert evidence['type'] == 'symlink'
    assert evidence['target'] == '/nonexistent/gdm.service'
    assert 'sha256' not in evidence


def test_baseline_missing_file_does_not_create_it(tmp_path):
    path = tmp_path / 'missing.conf'
    assert RECORDER['describe'](path)['type'] == 'absent'
    assert not path.exists()
