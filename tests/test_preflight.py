from copy import deepcopy
from pathlib import Path

import pytest

from desktopforge.detection import detect_system
from desktopforge.planning import build_plan
from desktopforge.preflight import inspect_preflight, preflight_preview
from desktopforge.session_layout import session_layout_preview
from desktopforge.recipes import RecipeError


def put(root, name, text='fixture'):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def inventory(root, config_home=None):
    result = detect_system(root=root, environ={}, which=lambda _: None, config_home=config_home)
    result['distribution'].update(id='fedora', version_id='45')
    result['display_manager']['name'] = 'sddm'
    return result


def test_static_observation_never_means_installable(tmp_path):
    result = inventory(tmp_path, tmp_path / 'home/user/.config')
    assert result['schema_version'] == 6
    assert result['preflight_evidence']['inspection_complete']
    assert result['preflight_evidence']['ostree_boot_marker'] == 'absent'
    preview = build_plan(result, 'niri', 'noctalia')
    assert preview['preflight']['status'] == 'observed'
    assert preview['status'] == 'blocked' and not preview['executable']
    assert preview['session_configuration_preview']['complete'] is False


def test_realistic_bootstrap_masks_and_wrappers_are_review_hints(tmp_path):
    put(tmp_path, 'usr/lib/systemd/user/niri.service.d/ryoku-bootstrap.conf', '[Unit]\nWants=ryoku-bootstrap.service\n')
    put(tmp_path, 'etc/sddm.conf.d/50-local-session-router.conf', '[Wayland]\nSessionCommand=/fixture/router\n')
    config = tmp_path / 'home/user/.config'
    mask = config / 'systemd/user/ryoku-bootstrap.service'
    mask.parent.mkdir(parents=True)
    mask.symlink_to('/dev/null')
    put(tmp_path, 'etc/systemd/user/default.target.wants/ryoku-bootstrap.service')
    result = inventory(tmp_path, config)
    preview = build_plan(result, 'niri', 'noctalia')
    assert preview['preflight']['status'] == 'review_required'
    paths = [item['path'] for item in preview['preflight']['findings']]
    assert '/usr/lib/systemd/user/niri.service.d/ryoku-bootstrap.conf' in paths
    assert '/etc/sddm.conf.d/50-local-session-router.conf' in paths
    assert '/home/user/.config/systemd/user/ryoku-bootstrap.service' in paths
    assert '/etc/systemd/user/default.target.wants/ryoku-bootstrap.service' in paths
    assert not result['preflight_evidence']['inspection_complete']
    assert 'Wants=ryoku-bootstrap.service' not in str(preview)  # no file text is exposed


def test_broken_session_symlink_and_managed_paths_reserve_ids(tmp_path):
    session = tmp_path / 'usr/share/wayland-sessions/desktopforge-niri-noctalia.desktop'
    session.parent.mkdir(parents=True)
    session.symlink_to('/nonexistent/launcher')
    put(tmp_path, 'usr/libexec/desktopforge/sessions/desktopforge-niri-noctalia-2')
    config = tmp_path / 'home/user/.config'
    put(tmp_path, 'home/user/.config/desktopforge/sessions/desktopforge-niri-noctalia-3')
    result = inventory(tmp_path, config)
    assert not result['sessions']['wayland']  # ordinary inventory skips broken files
    preview = build_plan(result, 'niri', 'noctalia')
    assert preview['session_id_preview'] == 'desktopforge-niri-noctalia-4'
    layout = preview['session_configuration_preview']
    assert layout['user_config']['relative_path'].endswith('desktopforge-niri-noctalia-4/niri.kdl')
    assert all('desktopforge-niri-noctalia-4' in entry['path'] for entry in layout['system_files'])


def test_symlinked_directory_is_not_traversed(tmp_path):
    outside = tmp_path / 'outside'
    put(outside, 'secret.conf', 'must not be read')
    directory = tmp_path / 'usr/lib/systemd/user/niri.service.d'
    directory.parent.mkdir(parents=True)
    directory.symlink_to(outside, target_is_directory=True)
    result = inspect_preflight(tmp_path, None)
    assert not result['inspection_complete']
    assert any(item['path'] == '/usr/lib/systemd/user/niri.service.d' and item['state'] == 'symlink'
               for item in result['observations'])
    assert 'secret.conf' not in str(result)


def test_unreadable_directory_and_marker_are_explicit_unknown(tmp_path, monkeypatch):
    directory = tmp_path / 'etc/sddm.conf.d'
    directory.mkdir(parents=True)
    real_iterdir = Path.iterdir
    real_lstat = Path.lstat

    def iterdir(path):
        if path == directory:
            raise PermissionError('fixture')
        return real_iterdir(path)

    def lstat(path, *args, **kwargs):
        if path == tmp_path / 'run':
            raise PermissionError('fixture')
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'iterdir', iterdir)
    monkeypatch.setattr(Path, 'lstat', lstat)
    result = inspect_preflight(tmp_path, tmp_path / 'home/user/.config')
    assert result['ostree_boot_marker'] == 'unknown'
    assert not result['inspection_complete']
    assert any(item['state'] == 'unknown' for item in result['observations'])
    assert preflight_preview(result)['blockers']


def test_ostree_marker_suppresses_dnf_recipe_proposals(tmp_path):
    put(tmp_path, 'run/ostree-booted')
    result = build_plan(inventory(tmp_path), 'niri', 'noctalia')
    assert result['operations'] == []
    assert result['session_configuration_preview'] is None
    assert any('OSTree' in item for item in result['blockers'])


def test_missing_or_out_of_tree_user_context_is_not_borrowed(tmp_path):
    result = inspect_preflight(tmp_path, tmp_path.parent / 'other-home')
    assert result['user_context'] == 'unknown'
    assert not result['inspection_complete']
    result = inventory(tmp_path)
    assert result['preflight_evidence']['user_context'] == 'unknown'
    assert preflight_preview(None)['status'] == 'incomplete'


def test_wrong_directory_type_is_incomplete(tmp_path):
    put(tmp_path, 'etc/sddm.conf.d')
    assert not inspect_preflight(tmp_path, tmp_path / 'home/user/.config')['inspection_complete']


def test_inspection_is_deterministic_and_writes_nothing(tmp_path, monkeypatch):
    put(tmp_path, 'etc/environment.d/z.conf')
    put(tmp_path, 'etc/environment.d/a.conf')
    before = {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    # A fixed-path preflight only needs lstat/listing, never file contents.
    def forbidden(*args, **kwargs):
        raise AssertionError('preflight must not read file contents')
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'read_text', forbidden)
        patch.setattr(Path, 'read_bytes', forbidden)
        first = inspect_preflight(tmp_path, None)
        assert first == inspect_preflight(tmp_path, None)
    assert before == {str(path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    data = inventory(tmp_path)
    saved = deepcopy(data)
    assert build_plan(data, 'niri', 'noctalia') == build_plan(data, 'niri', 'noctalia')
    assert data == saved


def test_layout_is_explicitly_incomplete_and_target_specific():
    layout = session_layout_preview('niri-noctalia-v5', 'desktopforge-niri-noctalia', 'niri', 'noctalia')
    assert layout['user_config']['relative_path'].startswith('desktopforge/sessions/')
    assert layout['user_config']['fragment_preview'] == 'spawn-at-startup "noctalia"\n'
    assert layout['system_files'][1]['content_preview'] is None
    assert layout['launch_contract']['compositor_argv'] == ['/usr/bin/niri', '--config', '<generated-private-config>']
    assert not layout['executable'] and not layout['complete']
    assert session_layout_preview('niri-noctalia-v5', 'desktopforge-niri-ryoku', 'niri', 'ryoku') is None
    with pytest.raises(RecipeError):
        session_layout_preview('niri-noctalia-v5', '../escape', 'niri', 'noctalia')


def test_cli_surfaces_layout_and_conflict_paths(tmp_path, monkeypatch, capsys):
    from desktopforge.cli import main

    put(tmp_path, 'etc/sddm.conf.d/router.conf')
    data = inventory(tmp_path, tmp_path / 'home/user/.config')
    monkeypatch.setattr('desktopforge.cli.detect_system', lambda: data)
    assert main(['plan', '--compositor', 'niri', '--shell', 'noctalia']) == 1
    text = capsys.readouterr().out
    assert 'Review: /etc/sddm.conf.d/router.conf' in text
    assert 'Isolated user config draft: desktopforge/sessions/' in text
    assert 'System file draft: /usr/libexec/desktopforge/sessions/' in text
    assert 'incomplete design previews' in text


def test_fixture_never_borrows_host_home_from_environment(tmp_path):
    result = detect_system(root=tmp_path, environ={'HOME': '/home/not-the-fixture',
        'XDG_CONFIG_HOME': '/outside/config'}, which=lambda _: None)
    assert result['preflight_evidence']['user_context'] == 'unknown'
    assert not any('not-the-fixture' in item['path'] or 'outside' in item['path']
                   for item in result['preflight_evidence']['coverage'])
