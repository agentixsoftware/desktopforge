"""Validation evidence for recipes: what was tested, where, on which code, with what result.

Evidence lives in validation/<recipe-id>/r<revision>.json. It is bound to the
recipe's content by a fingerprint, and every case names the commit it ran on,
so a later change to the helper, launcher or template makes the case stale
instead of silently counting. Approval itself (owner sign-off) is separate.
"""
import hashlib
import json
import re

SCHEMA = 1
LAB_CASES = {
    'preview-disclosure': 'Preview lists packages, files, notes and blockers before authorization',
    'install-gdm': 'Install on a GDM baseline (Polkit dialog, record written)',
    'login-logout-gdm': 'Session logs in from GDM; logout leaves no processes, variables or runtime files',
    'original-desktop-gdm': 'Original GNOME session still logs in afterwards (GDM)',
    'install-sddm': 'Install on an SDDM baseline; pre-existing packages recorded as such',
    'login-logout-sddm': 'Session logs in from SDDM; logout cleanup; launcher log in the journal',
    'original-desktop-sddm': 'Original desktop still logs in afterwards (SDDM); SDDM configuration unchanged',
    'reboot-installed': 'Installation survives a reboot and the session starts on a fresh boot',
    'reboot-during-session': 'Reboot from inside the session: launcher cleans up during shutdown',
    'failed-install-retry': 'Failed install (network) reports verified "no changes"; retry succeeds',
    'software-rendering-blocked': 'Software-only rendering blocks the plan and warns on an existing install',
    'no-display-fallback': 'Without a usable display the launcher ends the session and the login screen returns',
    'removal': 'Removal returns the package set and preservation record to the baseline',
    'reinstall-after-removal': 'Reinstall after removal succeeds',
    'removal-keeps-edited-file': 'Removal keeps an edited file and reports why',
    'repair-missing-file': 'Repair restores a missing file byte-identically',
    'repair-missing-package': 'Repair reinstalls a missing package at its recorded version',
    'repair-refuses-edited-file': 'Repair refuses to overwrite an edited file and explains how to proceed',
    'dependency-reverification': 'A removed dependency marks the installation modified; restoring it clears that',
}
HARDWARE_CASES = {
    'real-gpu-intel': 'Full install/login/logout/removal on real Intel graphics',
    'real-gpu-amd': 'Full install/login/logout/removal on real AMD graphics',
}
RESULTS = ('pass', 'fail')
# Code whose change since a case's commit makes that case stale.
CODE_PATHS = ('src/desktopforge/helper', 'src/desktopforge/helperd', 'src/desktopforge/loginsession.py',
              'src/desktopforge/data/templates')
COMMIT = re.compile(r'[0-9a-f]{7,40}')
DATE = re.compile(r'\d{4}-\d{2}-\d{2}')


class EvidenceError(Exception):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def fingerprint(recipe: dict, launcher_path: str, templates: dict[str, str]) -> str:
    """SHA-256 over what the recipe installs; independent of profile paths and status."""
    body = {k: v for k, v in recipe.items() if k != 'status'}
    text = _canonical(body).replace(launcher_path, '@launcher')
    names = sorted({op['template'] for op in recipe.get('operations', []) if 'template' in op})
    used = {name: hashlib.sha256(templates[name].encode()).hexdigest() for name in names}
    return hashlib.sha256((text + _canonical(used)).encode()).hexdigest()


def validate(evidence: dict) -> dict:
    def need(condition, message):
        if not condition:
            raise EvidenceError(message)
    need(isinstance(evidence, dict) and set(evidence) == {'schema', 'recipe', 'environments', 'cases', 'packages'},
         'evidence must have exactly: schema, recipe, environments, cases, packages')
    need(evidence['schema'] == SCHEMA, 'unsupported evidence schema')
    recipe = evidence['recipe']
    need(isinstance(recipe, dict) and set(recipe) == {'id', 'revision', 'fingerprint'}, 'recipe block')
    need(isinstance(recipe['fingerprint'], str) and re.fullmatch(r'[0-9a-f]{64}', recipe['fingerprint']), 'fingerprint')
    environments = evidence['environments']
    need(isinstance(environments, dict) and environments, 'environments')
    for name, env in environments.items():
        need(re.fullmatch(r'[a-z0-9-]{1,40}', name) is not None, f'environment name {name!r}')
        need(isinstance(env, dict) and env.get('kind') in ('vm', 'hardware')
             and {'kind', 'description', 'display_manager', 'renderer'} == set(env), f'environment {name}')
    seen = set()
    for case in evidence['cases']:
        need(isinstance(case, dict) and set(case) == {'id', 'environment', 'result', 'date', 'commit', 'reference'},
             'case fields')
        need(case['id'] in LAB_CASES or case['id'] in HARDWARE_CASES, f'unknown case {case["id"]!r}')
        need(case['environment'] in environments, f'case {case["id"]}: unknown environment')
        need(case['result'] in RESULTS, f'case {case["id"]}: result')
        need(DATE.fullmatch(case['date']) is not None and COMMIT.fullmatch(case['commit']) is not None,
             f'case {case["id"]}: date or commit')
        if case['id'] in HARDWARE_CASES:
            need(environments[case['environment']]['kind'] == 'hardware', f'{case["id"]} must run on hardware')
        seen.add((case['id'], case['environment']))
    need(len(seen) == len(evidence['cases']), 'duplicate case/environment entries')
    for package in evidence['packages']:
        need(isinstance(package, dict) and set(package) == {'name', 'evr'}, 'package entry')
    return evidence


def assess(evidence: dict, current_fingerprint: str, changed_since=lambda commit: False) -> dict:
    """Which tier the evidence supports right now, and exactly what is missing.

    changed_since(commit) -> True if helper/launcher/template code changed since
    that commit; such cases are stale and do not count.
    """
    validate(evidence)
    matches = evidence['recipe']['fingerprint'] == current_fingerprint
    passed, failed, stale = set(), [], []
    for case in evidence['cases']:
        if case['result'] == 'fail':
            failed.append(case['id'])
        elif changed_since(case['commit']):
            stale.append(case['id'])
        else:
            passed.add(case['id'])
    missing_lab = sorted(set(LAB_CASES) - passed)
    missing_hardware = sorted(set(HARDWARE_CASES) - passed)
    if not matches or failed or missing_lab:
        tier = 'not-validated'
    elif missing_hardware:
        tier = 'lab-validated'
    else:
        tier = 'approvable'  # still needs review and the owner's signed sign-off
    return {'tier': tier, 'fingerprint_matches': matches, 'failed': sorted(set(failed)),
            'stale': sorted(set(stale) - passed), 'missing_lab': missing_lab, 'missing_hardware': missing_hardware}
