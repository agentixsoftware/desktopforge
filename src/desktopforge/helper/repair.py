"""Plan the repair of one recorded installation. Pure: all evidence is passed in.

Repair restores what the install record says should exist, never something
different: missing files only when the current recipe renders exactly the
recorded content, missing packages only at the recorded version. Edited or
replaced files are never overwritten.
"""
import hashlib


def expected_files(recipe_plan, targets, render, session_filename, allowed_commands):
    """path -> (operation, sha256) for every file the recipe would create now."""
    expected = {}
    for op in recipe_plan['operations']:
        if op['op'] == 'create_file':
            data = op['content'].encode()
            expected[f'{targets[op["target"]]}/{op["name"]}'] = (op, hashlib.sha256(data).hexdigest())
        elif op['op'] == 'register_session':
            data = render(op['entry'], allowed_commands)
            expected[f'{targets[op["target"]]}/{session_filename(op["id"])}'] = (op, hashlib.sha256(data).hexdigest())
    return expected


def plan_repair(record, file_states, expected, installed_now, resolve, recipe_plan):
    """Return {'operations', 'blockers', 'restore'} for this installation."""
    blockers, file_ops, restore_files = [], [], []
    for item in record['files']:
        status = file_states.get(item['path'], 'unreadable')
        if status == 'intact':
            continue
        if status == 'missing':
            op, digest = expected.get(item['path'], (None, None))
            if op is None or digest != item['sha256']:
                blockers.append(f'Cannot restore {item["path"]}: the recipe would now produce different content.')
            else:
                file_ops.append(op)
                restore_files.append(item['path'])
        elif status == 'modified':
            blockers.append(f'{item["path"]} was edited; repair does not overwrite it. '
                            'Move it aside to have the original restored.')
        else:
            blockers.append(f'{item["path"]} is {status}; repair will not replace it.')
    missing_installed = [p for p in record['packages']['installed']
                         if not any(x['arch'] == p['arch'] for x in installed_now.get(p['name'], []))]
    missing_reused = [n for n in record['packages']['reused'] if not installed_now.get(n)]
    operations = []
    names = sorted({p['name'] for p in missing_installed} | set(missing_reused))
    if names:
        install = next((op for op in recipe_plan['operations'] if op['op'] == 'install_packages'), None)
        repositories = install['repositories'] if install else ['fedora', 'updates']
        rows, package_blockers = resolve(names, repositories)
        blockers += package_blockers
        resolved = {r['name']: r for r in rows}
        for package in missing_installed:
            row = resolved.get(package['name'])
            if row is None or row['evr'] != package['evr']:
                found = row['evr'] if row else 'nothing'
                blockers.append(f'{package["name"]} {package["evr"]} is no longer available '
                                f'(the repositories offer {found}); repair does not change versions.')
        extra = sorted(set(resolved) - set(names))
        if extra:
            blockers.append('Repair would also install packages this installation did not record: ' + ', '.join(extra))
        operations.append({'op': 'install_packages', 'packages': names, 'repositories': repositories,
                           'expected': sorted(rows, key=lambda r: (r['name'], r['arch']))})
    # Config, then validation, then the session entry: the login screen offers the
    # session again only once everything it needs is back.
    configs = [op for op in file_ops if op['op'] == 'create_file']
    entries = [op for op in file_ops if op['op'] == 'register_session']
    operations += configs
    if configs:
        operations += [op for op in recipe_plan['operations'] if op['op'] == 'validate_config']
    operations += entries
    if not operations and not blockers:
        blockers.append('Nothing needs repair: the installation is intact.')
    return {'operations': operations, 'blockers': blockers,
            'restore': {'files': restore_files, 'packages': names}}
