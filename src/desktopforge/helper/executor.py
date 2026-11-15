"""Execute a fixed, typed operation list with journaling. Never claims rollback."""
import hashlib

from . import fsops
from .evidence import canonical
from .journal import JournalError

OPERATIONS = ('create_file', 'fail')


class OperationFailed(Exception):
    pass


def plan_hash(plan):
    return hashlib.sha256(canonical(plan).encode()).hexdigest()


def _recovery(created):
    if not created:
        return 'No changes were made.'
    names = ', '.join(c['name'] for c in created)
    return f'Not rolled back. Review and remove if unwanted: {names}.'


def execute(plan, journal, target_fd):
    """Apply plan['operations'] in order beneath target_fd.

    The journal entry for each step is written before the step; a journal failure
    stops execution. Results report exactly what was created.
    """
    created = []
    state = None
    try:
        journal.record('applying', plan_hash=plan_hash(plan), recipe=plan['recipe'],
                       revision=plan['revision'])
        for index, operation in enumerate(plan['operations']):
            journal.record('operation_started', index=index, op=operation.get('op'),
                           name=operation.get('name'))
            try:
                kind = operation.get('op')
                if kind == 'create_file':
                    digest = fsops.create_file(target_fd, operation['name'],
                                               operation['content'].encode(), operation['mode'])
                    created.append({'name': operation['name'], 'sha256': digest})
                elif kind == 'fail':
                    raise OperationFailed(operation.get('reason', 'injected failure'))
                else:
                    raise OperationFailed('unsupported operation')
            except (OperationFailed, fsops.Conflict, fsops.UnsafePath, OSError, KeyError) as exc:
                state = 'failed_manual_recovery' if created else 'failed_recoverable'
                journal.record('operation_failed', index=index, error=str(exc))
                journal.record(state, created=created, recovery=_recovery(created))
                return {'state': state, 'created': created, 'failed_index': index,
                        'error': str(exc), 'recovery': _recovery(created), 'rolled_back': False}
            journal.record('operation_succeeded', index=index)
        journal.record('verifying')
        for item in created:
            if fsops.hash_file(target_fd, item['name']) != item['sha256']:
                state = 'failed_manual_recovery'
                journal.record(state, created=created, error=f'verification failed: {item["name"]}')
                return {'state': state, 'created': created, 'error': 'verification failed',
                        'recovery': _recovery(created), 'rolled_back': False}
        journal.record('completed', created=created)
        return {'state': 'completed', 'created': created, 'recovery': None, 'rolled_back': False}
    except JournalError as exc:
        state = 'failed_manual_recovery' if created else 'failed_recoverable'
        return {'state': state, 'created': created, 'error': str(exc), 'journal_complete': False,
                'recovery': _recovery(created), 'rolled_back': False}
