"""Offline regression tests for the researched, still-blocked reference recipe."""
from copy import deepcopy
import json

import pytest

from desktopforge.cli import main
from desktopforge.detection import detect_system
from desktopforge.planner import plan as compatibility_plan
from desktopforge.planning import build_plan
from desktopforge.recipes import RecipeError, load_bundled_recipes, parse_recipe


@pytest.fixture
def reference(tmp_path):
    result = detect_system(root=tmp_path, environ={}, which=lambda _: None)
    result['distribution'].update(id='fedora', version_id='45')
    result['display_manager']['name'] = 'sddm'
    result['sessions']['wayland'] = [
        {'id': 'cosmic', 'name': 'COSMIC'},
        {'id': 'niri', 'name': 'Niri (Ryoku)'},
        {'id': 'niri-noctalia', 'name': 'Niri (Noctalia)'},
        {'id': 'desktopforge-niri-noctalia', 'name': 'Existing preview collision'},
    ]
    return result


@pytest.fixture
def metadata():
    return {
        'schema_version': 2, 'id': 'review-fixture', 'revision': 1, 'status': 'unverified',
        'constraints': {'distribution': 'fedora', 'versions': ['45'], 'compositor': 'niri',
                        'shell': 'noctalia', 'display_managers': ['sddm']},
        'operations': [],
        'review': {'sources': ['https://example.org/review'], 'blockers': ['Needs VM validation.']},
    }


@pytest.mark.parametrize('manager', ['gdm', 'sddm'])
def test_bundled_reference_proposes_packages_without_claiming_support(reference, manager):
    reference['display_manager']['name'] = manager
    before = deepcopy(reference)
    result = build_plan(reference, 'niri', 'noctalia')
    assert result == build_plan(reference, 'niri', 'noctalia')
    assert result['selected_recipe'] == {'id': 'fedora45-niri-noctalia', 'revision': 2}
    assert result['compatibility'] == 'unverified'
    assert result['dry_run'] and not result['executable'] and result['status'] == 'blocked'
    assert [op['id'] for op in result['operations']] == [
        'propose-packages', 'check-niri', 'check-niri-session', 'check-noctalia', 'propose-session']
    assert result['operations'][0]['packages'] == ['niri', 'noctalia']
    assert result['operations'][-1]['destination_preview'].endswith('desktopforge-niri-noctalia-2.desktop')
    assert result['preserve']['display_manager'] == manager
    assert result['preserve']['user_configuration']
    assert result['preserve']['existing_sessions'] == sorted(s['id'] for s in before['sessions']['wayland'])
    assert all(not op['executable'] for op in result['operations'])
    assert any('legacy v4' in blocker for blocker in result['blockers'])
    assert any('drop-ins' in blocker for blocker in result['blockers'])
    assert any('NIRI_CONFIG' in blocker for blocker in result['blockers'])
    assert len(result['recipe_sources']) == 5
    assert reference == before


@pytest.mark.parametrize('version,manager', [('44', 'sddm'), ('46', 'sddm'), ('45', 'lightdm'), (None, 'gdm')])
def test_outside_reference_constraints_shows_no_proposals(reference, version, manager):
    reference['distribution']['version_id'] = version
    reference['display_manager']['name'] = manager
    result = build_plan(reference, 'niri', 'noctalia')
    assert result['compatibility'] == 'unsupported'
    assert result['operations'] == [] and result['selected_recipe'] is None
    assert result['recipe_sources'] == []


def test_legacy_executable_presence_does_not_remove_review_blockers(reference):
    reference['shell_executables']['noctalia']['found'] = True
    result = build_plan(reference, 'niri', 'noctalia')
    assert any('legacy v4' in blocker for blocker in result['blockers'])
    assert result['status'] == 'blocked'


def test_compatibility_api_retains_real_recipe_proposals(reference):
    result = compatibility_plan(reference, 'niri', 'noctalia')
    assert len(result['operations']) == 5
    assert result['writes'] == result['package_commands'] == []
    assert result['recipe_sources']


def test_cli_exposes_real_recipe_sources_and_review_blockers(reference, monkeypatch, capsys):
    monkeypatch.setattr('desktopforge.cli.detect_system', lambda: reference)
    args = ['plan', '--compositor', 'niri', '--shell', 'noctalia']
    assert main(args) == 1
    text = capsys.readouterr().out
    assert 'propose-packages [system]' in text
    assert 'NIRI_CONFIG' in text
    assert 'Reference: https://packages.fedoraproject.org/pkgs/noctalia/noctalia/' in text
    assert main(args + ['--json']) == 1
    assert json.loads(capsys.readouterr().out)['recipe_sources']


@pytest.mark.parametrize('review', [None, {}, {'sources': [], 'blockers': ['test']},
    {'sources': ['https://example.org'], 'blockers': []},
    {'sources': ['https://example.org'], 'blockers': ['test'], 'verified': True}])
def test_review_structure_is_strict(metadata, review):
    metadata['review'] = review
    with pytest.raises(RecipeError):
        parse_recipe(metadata)


@pytest.mark.parametrize('source', ['file:///etc/passwd', 'http://example.org', 'javascript:alert(1)',
    'https://user:password@example.org', 'https://example.org/\nmalformed', 'https://[bad'])
def test_review_sources_are_reference_urls_only(metadata, source):
    metadata['review']['sources'] = [source]
    with pytest.raises(RecipeError):
        parse_recipe(metadata)


def test_review_order_is_canonical_and_never_removes_blockers(metadata, reference):
    metadata['review'] = {'sources': ['https://b.example.org', 'https://a.example.org'],
                          'blockers': ['Z review blocker.', 'A review blocker.']}
    first = parse_recipe(metadata)
    metadata['review']['sources'].reverse()
    metadata['review']['blockers'].reverse()
    assert first == parse_recipe(metadata)
    result = build_plan(reference, 'niri', 'noctalia', (first,))
    assert 'A review blocker.' in result['blockers']
    assert 'No validated installation recipe is available.' in result['blockers']
    metadata['schema_version'] = 1
    del metadata['operations']
    with pytest.raises(RecipeError):
        parse_recipe(metadata)


def test_all_bundled_recipes_validate():
    recipes = load_bundled_recipes()
    assert {recipe.id for recipe in recipes} == {'fedora45-niri-ryoku', 'fedora45-niri-noctalia'}
