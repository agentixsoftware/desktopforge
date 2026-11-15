import json

import pytest

from desktopforge.repositories import inspect_repositories, parse_repository_declarations


def test_collects_flags_without_urls_credentials_or_interpolation(tmp_path):
    folder = tmp_path / 'usr/share/dnf5/repos.d'
    folder.mkdir(parents=True)
    (folder / 'example.repo').write_text('[fedora]\nenabled=1\ngpgcheck=yes\nrepo_gpgcheck=0\nbaseurl=https://user:secret@example.org/$releasever\ngpgkey=https://private/key\n')
    report = inspect_repositories(tmp_path, 'fedora')
    row = report['declarations'][0]
    assert row['id'] == 'fedora'
    assert row['enabled'] == 'declared_on' and row['gpgcheck'] == 'declared_on'
    assert row['repo_gpgcheck'] == 'declared_off' and row['pkg_gpgcheck'] == 'unspecified'
    assert report['installed_package_origin'] == 'unknown'
    assert all(value not in json.dumps(report) for value in ('secret', 'https://', 'private/key'))


def test_defaults_are_not_invented():
    row = parse_repository_declarations('[fedora]\nname=Fedora\n')[0]
    assert row['enabled'] == row['gpgcheck'] == 'unspecified'
    assert parse_repository_declarations('[fedora]\nenabled=$variable\n')[0]['enabled'] == 'unknown'


def test_bad_file_does_not_hide_valid_file_or_leak_contents(tmp_path):
    folder = tmp_path / 'etc/yum.repos.d'
    folder.mkdir(parents=True)
    (folder / 'bad.repo').write_text('secret=do-not-expose\n')
    (folder / 'good.repo').write_text('[fedora]\nenabled=1\n')
    report = inspect_repositories(tmp_path, 'fedora')
    assert len(report['declarations']) == 1
    assert any(row['state'] == 'unreadable_or_invalid' for row in report['coverage'])
    assert 'do-not-expose' not in json.dumps(report)


def test_symlink_file_and_symlink_directory_are_not_followed(tmp_path):
    external = tmp_path / 'outside'
    external.mkdir()
    (external / 'private.repo').write_text('[private]\nenabled=1\n')
    folder = tmp_path / 'etc/yum.repos.d'
    folder.mkdir(parents=True)
    (folder / 'linked.repo').symlink_to(external / 'private.repo')
    (tmp_path / 'etc/distro.repos.d').symlink_to(external, target_is_directory=True)
    report = inspect_repositories(tmp_path, 'fedora')
    assert report['declarations'] == []
    assert len([row for row in report['coverage'] if row['state'] == 'symlink']) == 2


def test_duplicate_ids_remain_visible(tmp_path):
    folder = tmp_path / 'etc/yum.repos.d'
    folder.mkdir(parents=True)
    for name in ('a', 'b'):
        (folder / f'{name}.repo').write_text('[fedora]\nenabled=1\n')
    report = inspect_repositories(tmp_path, 'fedora')
    assert report['duplicate_ids'] == ['fedora'] and len(report['declarations']) == 2


def test_non_fedora_is_not_inspected(tmp_path):
    assert inspect_repositories(tmp_path, 'arch')['status'] == 'unavailable'
    assert inspect_repositories(tmp_path, 'arch')['coverage'] == []


@pytest.mark.parametrize('text', ['[bad/id]\nenabled=1\n', '[fedora]\nenabled=1\nenabled=0\n', '[DEFAULT]\nenabled=1\n[fedora]\n'])
def test_invalid_or_inherited_data_rejected(text):
    import configparser
    with pytest.raises((ValueError, configparser.Error)):
        parse_repository_declarations(text)
