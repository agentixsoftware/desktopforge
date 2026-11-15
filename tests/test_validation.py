"""Validation evidence: bound to recipe content and to current code; tiers and gaps are explicit."""
import copy
import json
from pathlib import Path
import runpy
import subprocess

import pytest

from desktopforge import validation

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = json.loads((REPO / 'validation/fedora45-niri-noctalia-lab/r2.json').read_text())
DAEMON = runpy.run_path(str(REPO / 'src/desktopforge/helperd/daemon.py'), init_globals={'PROFILE_NAME': 'lab'},
                        run_name='validation_tests')
TEMPLATES = {p.name: p.read_text() for p in (REPO / 'src/desktopforge/data/templates').glob('*')}
RECIPE = DAEMON['ALL_RECIPES']['fedora45-niri-noctalia-lab']
FP = validation.fingerprint(RECIPE, DAEMON['SESSION_LAUNCHER'], TEMPLATES)


def full(evidence, hardware=False):
    out = copy.deepcopy(evidence)
    out['cases'] = [c for c in out['cases'] if c['id'] in validation.LAB_CASES]
    if hardware:
        out['environments']['laptop-intel'] = {'kind': 'hardware', 'description': 'x', 'display_manager': 'gdm',
                                              'renderer': 'Mesa Intel'}
        out['environments']['desktop-amd'] = {'kind': 'hardware', 'description': 'y', 'display_manager': 'sddm',
                                             'renderer': 'AMD Radeon'}
        out['cases'] += [dict(out['cases'][0], id='real-gpu-intel', environment='laptop-intel'),
                         dict(out['cases'][0], id='real-gpu-amd', environment='desktop-amd')]
    return out


def test_committed_evidence_is_valid_and_matches_the_current_recipe():
    validation.validate(EVIDENCE)
    assert EVIDENCE['recipe']['fingerprint'] == FP
    assert {c['id'] for c in EVIDENCE['cases']} == set(validation.LAB_CASES)


def test_tiers():
    assert validation.assess(full(EVIDENCE), FP)['tier'] == 'lab-validated'
    assert validation.assess(full(EVIDENCE, hardware=True), FP)['tier'] == 'approvable'
    report = validation.assess(full(EVIDENCE), FP)
    assert report['missing_hardware'] == ['real-gpu-amd', 'real-gpu-intel']


def test_stale_cases_do_not_count():
    report = validation.assess(full(EVIDENCE), FP, changed_since=lambda commit: commit == '6319873')
    assert report['tier'] == 'not-validated'
    assert report['stale'] == ['reinstall-after-removal', 'removal', 'removal-keeps-edited-file']


def test_changed_recipe_or_failed_case_is_not_validated():
    assert validation.assess(full(EVIDENCE), 'f' * 64)['fingerprint_matches'] is False
    failing = full(EVIDENCE)
    failing['cases'][0]['result'] = 'fail'
    report = validation.assess(failing, FP)
    assert report['tier'] == 'not-validated' and report['failed'] == [failing['cases'][0]['id']]


def test_fingerprint_ignores_status_and_profile_paths_but_not_content():
    approved = dict(RECIPE, status='approved')
    assert validation.fingerprint(approved, DAEMON['SESSION_LAUNCHER'], TEMPLATES) == FP
    prod = runpy.run_path(str(REPO / 'src/desktopforge/helperd/daemon.py'), init_globals={'PROFILE_NAME': 'production'},
                          run_name='validation_prod')
    prod_recipe = prod['ALL_RECIPES']['fedora45-niri-noctalia-lab']
    assert validation.fingerprint(prod_recipe, prod['SESSION_LAUNCHER'], TEMPLATES) == FP  # same content, other paths
    changed_template = dict(TEMPLATES, **{'niri-noctalia.kdl': TEMPLATES['niri-noctalia.kdl'] + '\n// edit\n'})
    assert validation.fingerprint(RECIPE, DAEMON['SESSION_LAUNCHER'], changed_template) != FP
    changed_note = copy.deepcopy(RECIPE)
    changed_note['notes'] = changed_note['notes'] + ['another note']
    assert validation.fingerprint(changed_note, DAEMON['SESSION_LAUNCHER'], TEMPLATES) != FP


@pytest.mark.parametrize('mutate', [
    lambda e: e.update(extra=1),
    lambda e: e['cases'].append(dict(e['cases'][0])),                   # duplicate
    lambda e: e['cases'][0].update(id='made-up-case'),
    lambda e: e['cases'][0].update(result='mostly'),
    lambda e: e['cases'][0].update(environment='nowhere'),
    lambda e: e['cases'].append(dict(e['cases'][0], id='real-gpu-intel')),  # hardware case on a VM
    lambda e: e['recipe'].update(fingerprint='abc'),
])
def test_evidence_schema_is_strict(mutate):
    evidence = copy.deepcopy(EVIDENCE)
    mutate(evidence)
    with pytest.raises(validation.EvidenceError):
        validation.validate(evidence)


def test_report_script_exit_codes():
    script = str(REPO / 'scripts/validation-report')
    evidence = str(REPO / 'validation/fedora45-niri-noctalia-lab/r2.json')
    result = subprocess.run([script, evidence], capture_output=True, text=True)
    assert result.returncode == 0 and 'fedora45-niri-noctalia-lab r2:' in result.stdout
    strict = subprocess.run([script, evidence, '--require', 'approvable'], capture_output=True, text=True)
    assert strict.returncode == 1 and 'hardware cases still needed: real-gpu-amd, real-gpu-intel' in strict.stdout
