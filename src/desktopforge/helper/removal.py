"""Plan the removal of one recorded installation. Pure: all evidence is passed in.

Only what the install record says this installation created or installed is
eligible. Files must still match their recorded hash; packages must still be
installed at the recorded version and removable without taking anything else
with them. Everything else is kept and reported with a reason.
"""
import os

# Session entry first: the login screen stops offering the session before the
# files it depends on disappear.
ROLE_ORDER = ('session-entry', 'session-config')
ROLE_TARGETS = {'session-entry': 'sessions', 'session-config': 'session-config'}


def plan_removal(record, file_states, installed_now, resolve_removal):
    """Return {'operations', 'kept', 'blockers'}.

    file_states: path -> intact|modified|missing|unsafe|unreadable
    installed_now: name -> list of {'evr', 'arch'} currently installed ([] if absent)
    resolve_removal(names) -> (rows, blockers) from a dry run
    """
    operations, blockers = [], []
    kept_files, kept_packages = [], []
    for item in sorted(record['files'], key=lambda f: ROLE_ORDER.index(f['role'])):
        status = file_states.get(item['path'], 'unreadable')
        if status == 'intact':
            operations.append({'op': 'remove_file', 'target': ROLE_TARGETS[item['role']],
                               'name': os.path.basename(item['path']), 'path': item['path'],
                               'sha256': item['sha256']})
        else:
            kept_files.append({'path': item['path'], 'reason': status})
    candidates = []
    for package in record['packages']['installed']:
        same_arch = [p for p in installed_now.get(package['name'], []) if p['arch'] == package['arch']]
        if not same_arch:
            kept_packages.append({'name': package['name'], 'evr': package['evr'], 'reason': 'not-installed'})
        elif any(p['evr'] == package['evr'] for p in same_arch):
            candidates.append(package)
        elif len(same_arch) == 1:
            # This installation added the package; normal updates since then do not change that.
            candidates.append(dict(package, evr=same_arch[0]['evr']))
        else:
            kept_packages.append({'name': package['name'], 'evr': package['evr'], 'reason': 'changed'})
    for name in record['packages']['reused']:
        kept_packages.append({'name': name, 'evr': None, 'reason': 'reused'})
    if candidates:
        names = sorted({p['name'] for p in candidates})
        rows, package_blockers = resolve_removal(names)
        blockers += package_blockers
        recorded = {(p['name'], p['arch'], p['evr']) for p in candidates}
        resolved = {(r['name'], r['arch'], r['evr']) for r in rows}
        if not package_blockers and resolved != recorded:
            blockers.append('The package manager would not remove exactly the recorded packages and versions.')
        operations.append({'op': 'remove_packages', 'packages': names,
                           'expected': sorted(rows, key=lambda r: (r['name'], r['arch']))})
    if not operations:
        blockers.append('Nothing recorded by this installation can be removed safely.')
    return {'operations': operations, 'blockers': blockers,
            'kept': {'files': kept_files, 'packages': sorted(kept_packages, key=lambda p: p['name'])}}
