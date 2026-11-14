import json

import pytest

from desktopforge.cli import main
from desktopforge.detection import detect_system
from desktopforge.planning import build_plan, compatibility_catalog


def inventory(tmp_path):
    return detect_system(root=tmp_path, environ={}, which=lambda _: None)


def test_catalog_never_claims_verified_support():
    entries = compatibility_catalog()
    assert len(entries) == 18
    assert all(entry['status'] == 'unverified' for entry in entries)


def test_plan_is_deterministic_blocked_and_preserves_sessions(tmp_path):
    data = inventory(tmp_path)
    data['distribution'].update(id='fedora', version_id='45')
    data['sessions']['wayland'] = [
        {'id': 'desktopforge-niri-ryoku'}, {'id': 'desktopforge-niri-ryoku-2'}]
    before = json.dumps(data, sort_keys=True)
    plan = build_plan(data, 'niri', 'ryoku')
    assert plan == build_plan(data, 'niri', 'ryoku')
    assert plan['session_id_preview'] == 'desktopforge-niri-ryoku-3'
    assert plan['compatibility'] == 'unverified'
    assert plan['status'] == 'blocked'
    assert plan['operations'] == []
    assert json.dumps(data, sort_keys=True) == before


def test_unknown_distribution_and_target_fail_closed(tmp_path):
    data = inventory(tmp_path)
    assert build_plan(data, 'niri', 'ryoku')['compatibility'] == 'unsupported'
    with pytest.raises(ValueError):
        build_plan(data, '../niri', 'ryoku')


def test_cli_list_and_blocked_plan_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr('desktopforge.cli.detect_system', lambda: inventory(tmp_path))
    assert main(['list', '--json']) == 0
    assert len(json.loads(capsys.readouterr().out)) == 18
    assert main(['plan', '--compositor', 'niri', '--shell', 'ryoku', '--json']) == 1
    assert json.loads(capsys.readouterr().out)['operations'] == []
