"""Typed proposals only: this module never executes commands or writes files."""
from __future__ import annotations

from dataclasses import dataclass
import heapq
import re
from typing import Literal

from .errors import RecipeError


@dataclass(frozen=True)
class DependencyCheck:
    id: str
    depends_on: tuple[str, ...]
    executable: str
    type: Literal['dependency_check'] = 'dependency_check'


@dataclass(frozen=True)
class PackageProposal:
    id: str
    depends_on: tuple[str, ...]
    package_manager: str
    packages: tuple[str, ...]
    type: Literal['package_proposal'] = 'package_proposal'


@dataclass(frozen=True)
class SessionProposal:
    id: str
    depends_on: tuple[str, ...]
    template: str
    type: Literal['session_proposal'] = 'session_proposal'


Operation = DependencyCheck | PackageProposal | SessionProposal


def _slug(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', value) is not None


def parse_operations(data: object) -> tuple[Operation, ...]:
    if not isinstance(data, list):
        raise RecipeError('operations must be a list')
    operations = []
    for entry in data:
        if not isinstance(entry, dict):
            raise RecipeError('Each operation must be an object')
        kind = entry.get('type')
        fields = {
            'dependency_check': {'executable'},
            'package_proposal': {'package_manager', 'packages'},
            'session_proposal': {'template'},
        }
        if not isinstance(kind, str) or kind not in fields:
            raise RecipeError('Unsupported operation type')
        if set(entry) != {'id', 'type', 'depends_on'} | fields[kind]:
            raise RecipeError(f'Unexpected or missing fields for {kind}')
        if not _slug(entry['id']):
            raise RecipeError('Operation id must be a lowercase slug')
        dependencies = entry['depends_on']
        if (not isinstance(dependencies, list) or any(not _slug(item) for item in dependencies)
                or len(set(dependencies)) != len(dependencies)):
            raise RecipeError('depends_on must contain unique operation IDs')
        common = {'id': entry['id'], 'depends_on': tuple(sorted(dependencies))}
        if kind == 'dependency_check':
            executable = entry['executable']
            if not isinstance(executable, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]*', executable):
                raise RecipeError('Dependency executable must be a basename, without arguments')
            operation = DependencyCheck(**common, executable=executable)
        elif kind == 'package_proposal':
            if entry['package_manager'] not in ('dnf', 'dnf5', 'pacman'):
                raise RecipeError('Unsupported package manager')
            packages = entry['packages']
            if (not isinstance(packages, list) or not packages
                    or any(not isinstance(item, str) or not re.fullmatch(r'[a-z0-9][a-z0-9+_.-]*', item) for item in packages)
                    or len(set(packages)) != len(packages)):
                raise RecipeError('packages must contain unique plain package names')
            operation = PackageProposal(**common, package_manager=entry['package_manager'], packages=tuple(sorted(packages)))
        else:
            if not _slug(entry['template']):
                raise RecipeError('Session template must be a bundled template ID, not a path')
            operation = SessionProposal(**common, template=entry['template'])
        operations.append(operation)
    if sum(isinstance(op, SessionProposal) for op in operations) > 1:
        raise RecipeError("Only one session proposal is allowed per recipe")
    return order_operations(tuple(operations))


def order_operations(operations: tuple[Operation, ...]) -> tuple[Operation, ...]:
    """Topological order with lexical tie-breaking, independent of input order."""
    by_id = {operation.id: operation for operation in operations}
    if len(by_id) != len(operations):
        raise RecipeError('Duplicate operation IDs')
    incoming = {operation.id: len(operation.depends_on) for operation in operations}
    children: dict[str, list[str]] = {name: [] for name in by_id}
    for operation in operations:
        for dependency in operation.depends_on:
            if dependency not in by_id:
                raise RecipeError(f'Unknown dependency {dependency} for {operation.id}')
            children[dependency].append(operation.id)
    ready = [name for name, count in incoming.items() if count == 0]
    heapq.heapify(ready)
    ordered = []
    while ready:
        name = heapq.heappop(ready)
        ordered.append(by_id[name])
        for child in children[name]:
            incoming[child] -= 1
            if incoming[child] == 0:
                heapq.heappush(ready, child)
    if len(ordered) != len(operations):
        raise RecipeError('Operation dependency cycle')
    return tuple(ordered)


def operation_preview(operation: Operation, session_id: str) -> dict:
    common = {'id': operation.id, 'type': operation.type,
              'depends_on': list(operation.depends_on), 'executable': False}
    if isinstance(operation, DependencyCheck):
        return {**common, 'privilege': 'none', 'proposed_changes': [],
                'executable_name': operation.executable,
                'summary': f'Check executable availability: {operation.executable} (not performed).'}
    if isinstance(operation, PackageProposal):
        return {**common, 'privilege': 'system', 'packages': list(operation.packages),
                'package_manager': operation.package_manager,
                'proposed_changes': ['system_packages'],
                'summary': f'Propose packages via {operation.package_manager}: {", ".join(operation.packages)}.'}
    destination = f'/usr/share/wayland-sessions/{session_id}.desktop'
    return {**common, 'privilege': 'system', 'template': operation.template,
            'destination_preview': destination, 'overwrite': False,
            'proposed_changes': [destination],
            'summary': f'Propose a new session file: {destination}; preserve existing files.'}
