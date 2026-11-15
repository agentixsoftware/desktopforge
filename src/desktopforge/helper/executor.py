"""Execute a fixed, typed operation list with journaling. Never claims rollback."""
import hashlib

from . import fsops, sessions
from .evidence import canonical
from .journal import JournalError

OPERATIONS = ('create_file', 'register_session', 'fail')


class OperationFailed(Exception):
    pass


def plan_hash(plan):
    return hashlib.sha256(canonical(plan).encode()).hexdigest()


def _recovery(created):
    if not created:
        return 'No changes were made.'
    names = ', '.join(f'{c["target"]}/{c["name"]}' for c in created)
    return f'Not rolled back. Review and remove if unwanted: {names}.'


def _run(operation, targets, allowed_commands):
    kind = operation.get('op')
    if kind == 'fail':
        raise OperationFailed(operation.get('reason', 'injected failure'))
    if kind not in OPERATIONS:
        raise OperationFailed('unsupported operation')
    target = operation['target']
    if target not in targets:
        raise OperationFailed('unknown operation target')
    if kind == 'create_file':
        name, data, mode = operation['name'], operation['content'].encode(), operation['mode']
    else:
        name = sessions.session_filename(operation['id'])
        data, mode = sessions.render(operation['entry'], allowed_commands), 0o644
    digest = fsops.create_file(targets[target], name, data, mode)
    return {'target': target, 'name': name, 'sha256': digest}


def execute(plan, journal, targets, allowed_commands=frozenset()):
    """Apply plan['operations'] in order; targets maps names to directory handles.

    The journal entry for each step is written before the step; a journal failure
    stops execution. Results report exactly what was created.
    """
    created = []
    try:
        journal.record('applying', plan_hash=plan_hash(plan), recipe=plan['recipe'],
                       revision=plan['revision'])
        for index, operation in enumerate(plan['operations']):
            journal.record('operation_started', index=index, op=operation.get('op'),
                           name=operation.get('name') or operation.get('id'))
            try:
                created.append(_run(operation, targets, allowed_commands))
            except (OperationFailed, fsops.Conflict, fsops.UnsafePath, sessions.InvalidEntry,
                    OSError, KeyError, AttributeError) as exc:
                state = 'failed_manual_recovery' if created else 'failed_recoverable'
                journal.record('operation_failed', index=index, error=str(exc))
                journal.record(state, created=created, recovery=_recovery(created))
                return {'state': state, 'created': created, 'failed_index': index,
                        'error': str(exc), 'recovery': _recovery(created), 'rolled_back': False}
            journal.record('operation_succeeded', index=index, created=created[-1])
        journal.record('verifying')
        for item in created:
            if fsops.hash_file(targets[item['target']], item['name']) != item['sha256']:
                journal.record('failed_manual_recovery', created=created,
                               error=f'verification failed: {item["name"]}')
                return {'state': 'failed_manual_recovery', 'created': created,
                        'error': 'verification failed', 'recovery': _recovery(created),
                        'rolled_back': False}
        journal.record('completed', created=created)
        return {'state': 'completed', 'created': created, 'recovery': None, 'rolled_back': False}
    except JournalError as exc:
        state = 'failed_manual_recovery' if created else 'failed_recoverable'
        return {'state': state, 'created': created, 'error': str(exc), 'journal_complete': False,
                'recovery': _recovery(created), 'rolled_back': False}
