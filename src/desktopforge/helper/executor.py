"""Execute a fixed, typed operation list with journaling. Never claims rollback."""
import hashlib

from . import fsops, pkgtx, sessions
from .evidence import canonical
from .journal import JournalError

OPERATIONS = ('install_packages', 'create_file', 'register_session', 'validate_config', 'fail')


class OperationFailed(Exception):
    pass


def plan_hash(plan):
    return hashlib.sha256(canonical(plan).encode()).hexdigest()


class Adapters:
    """Privileged side effects the executor may not perform itself.

    runner(argv) -> (status, output) runs a fixed argv with package-manager rights.
    validators maps a config kind to callable(dir_fd, name) -> (ok, message).
    """

    def __init__(self, runner=None, signer=None, validators=None):
        self.runner, self.signer, self.validators = runner, signer, validators or {}


def _describe(item):
    if item.get('kind') == 'packages':
        return 'packages ' + ' '.join(f'{p["name"]}-{p["evr"]}' for p in item['packages'])
    return f'{item["target"]}/{item["name"]}'


def _recovery(created):
    if not created:
        return 'No changes were made.'
    return 'Not rolled back. Review and remove if unwanted: ' + '; '.join(_describe(c) for c in created) + '.'


def _run(operation, targets, allowed_commands, adapters):
    kind = operation.get('op')
    if kind == 'fail':
        raise OperationFailed(operation.get('reason', 'injected failure'))
    if kind not in OPERATIONS:
        raise OperationFailed('unsupported operation')
    if kind == 'install_packages':
        if adapters.runner is None:
            raise OperationFailed('no package adapter available')
        records, _output = pkgtx.install(operation['packages'], operation['repositories'],
                                         operation['expected'], adapters.runner, adapters.signer)
        if not operation['expected']:
            return None  # everything was already installed: nothing created
        return {'kind': 'packages', 'packages': [
            {'name': r['name'], 'arch': r['arch'], 'evr': r['evr'], 'repo': r['repo'],
             'installtid': next((x['installtid'] for x in records.get(r['name'], [])
                                 if x['evr'] == r['evr']), None)} for r in operation['expected']]}
    target = operation['target']
    if target not in targets:
        raise OperationFailed('unknown operation target')
    if kind == 'validate_config':
        validator = adapters.validators.get(operation['kind'])
        if validator is None:
            raise OperationFailed('no validator for this configuration kind')
        ok, message = validator(targets[target], fsops.check_name(operation['name']))
        if not ok:
            raise OperationFailed(f'configuration rejected: {message[:300]}')
        return None
    if kind == 'create_file':
        name, data, mode = operation['name'], operation['content'].encode(), operation['mode']
    else:
        name = sessions.session_filename(operation['id'])
        data, mode = sessions.render(operation['entry'], allowed_commands), 0o644
    digest = fsops.create_file(targets[target], name, data, mode)
    return {'kind': 'file', 'target': target, 'name': name, 'sha256': digest}


def execute(plan, journal, targets, allowed_commands=frozenset(), adapters=None):
    """Apply plan['operations'] in order; targets maps names to directory handles.

    The journal entry for each step is written before the step; a journal failure
    stops execution. Results report exactly what was created or installed.
    """
    adapters = adapters or Adapters()
    created = []
    try:
        journal.record('applying', plan_hash=plan_hash(plan), recipe=plan['recipe'],
                       revision=plan['revision'])
        for index, operation in enumerate(plan['operations']):
            journal.record('operation_started', index=index, op=operation.get('op'),
                           name=operation.get('name') or operation.get('id'))
            try:
                item = _run(operation, targets, allowed_commands, adapters)
            except (OperationFailed, fsops.Conflict, fsops.UnsafePath, sessions.InvalidEntry,
                    pkgtx.PackageError, OSError, KeyError, AttributeError, TypeError) as exc:
                if operation.get('op') == 'install_packages' and adapters.runner is not None:
                    created.extend(_partial_packages(operation, adapters))
                state = 'failed_manual_recovery' if created else 'failed_recoverable'
                journal.record('operation_failed', index=index, error=str(exc))
                journal.record(state, created=created, recovery=_recovery(created))
                return {'state': state, 'created': created, 'failed_index': index,
                        'error': str(exc), 'recovery': _recovery(created), 'rolled_back': False}
            if item is not None:
                created.append(item)
            journal.record('operation_succeeded', index=index, created=item)
        journal.record('verifying')
        problems = _verify(created, targets, adapters)
        if problems:
            journal.record('failed_manual_recovery', created=created, error='; '.join(problems))
            return {'state': 'failed_manual_recovery', 'created': created,
                    'error': 'verification failed: ' + '; '.join(problems),
                    'recovery': _recovery(created), 'rolled_back': False}
        journal.record('completed', created=created)
        return {'state': 'completed', 'created': created, 'recovery': None, 'rolled_back': False}
    except JournalError as exc:
        state = 'failed_manual_recovery' if created else 'failed_recoverable'
        return {'state': state, 'created': created, 'error': str(exc), 'journal_complete': False,
                'recovery': _recovery(created), 'rolled_back': False}


def _partial_packages(operation, adapters):
    """After a failed transaction, report which reviewed packages are now present."""
    try:
        records, _missing = pkgtx.query_installed(sorted({r['name'] for r in operation['expected']}),
                                                  adapters.runner)
    except (pkgtx.PackageError, OSError):
        return [{'kind': 'packages', 'packages': [], 'unknown': True}]
    present = [dict(r, repo=r.get('repo')) for row in operation['expected']
               for r in records.get(row['name'], []) if r['evr'] == row['evr']]
    return [{'kind': 'packages', 'packages': present}] if present else []


def _verify(created, targets, adapters):
    problems = []
    for item in created:
        if item.get('kind') == 'packages':
            _records, issues = pkgtx.verify_installed(item['packages'], adapters.runner, adapters.signer)
            problems += issues
        elif fsops.hash_file(targets[item['target']], item['name']) != item['sha256']:
            problems.append(f'{item["name"]} changed after creation')
    return problems
