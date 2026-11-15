"""Declarative command requirements and pure assessment of supplied evidence."""
from dataclasses import dataclass
import re

from .errors import RecipeError


@dataclass(frozen=True)
class CommandRequirement:
    executable: str
    role: str
    package: str
    version_major: int | None


def parse_requirements(data: object) -> tuple[CommandRequirement, ...]:
    if not isinstance(data, list):
        raise RecipeError('requirements must be a list')
    result = []
    for item in data:
        if not isinstance(item, dict) or set(item) != {'executable', 'role', 'package', 'version_major'}:
            raise RecipeError('Each requirement needs executable, role, package and version_major')
        if not isinstance(item['executable'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]*', item['executable']):
            raise RecipeError('Requirement executable must be a basename')
        if not isinstance(item['package'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9_.+-]*', item['package']):
            raise RecipeError('Requirement package must be a plain package name')
        if item['role'] not in ('compositor', 'shell_launcher', 'session_launcher', 'management'):
            raise RecipeError('Unknown requirement role')
        major = item['version_major']
        if major is not None and (type(major) is not int or major < 0):
            raise RecipeError('version_major must be a nonnegative integer or null')
        result.append(CommandRequirement(**item))
    if len({r.executable for r in result}) != len(result):
        raise RecipeError('Duplicate requirement executable')
    return tuple(sorted(result, key=lambda r: r.executable))


def assess_requirements(requirements: tuple[CommandRequirement, ...], inventory: dict) -> dict:
    """Observe requirements; no finding authorizes reuse or installation."""
    packages = {p['name']: p for p in inventory.get('package_inventory', {}).get('packages', [])}
    owners = inventory.get('package_inventory', {}).get('executable_ownership', [])
    commands = inventory.get('command_evidence', {})
    findings = []
    for requirement in requirements:
        reasons = []
        command = commands.get(requirement.executable)
        status = 'observed'
        if command is None:
            status = 'unknown'
            reasons.append('Command was not inspected by this detector.')
        elif not command.get('found'):
            status = 'missing'
            reasons.append('Required command was not found on PATH.')
        elif not command.get('path'):
            status = 'unknown'
            reasons.append('Command path could not be resolved.')
        ownership = next((o for o in owners if o.get('executable') == requirement.executable
                          and command and o.get('path') == command.get('path')), None)
        if command and command.get('path'):
            if not ownership or ownership.get('status') != 'owned':
                status = 'unknown'
                reasons.append('RPM command ownership is unknown.')
            elif ownership.get('owners') != [requirement.package]:
                status = 'mismatch'
                reasons.append(f'Command owner does not uniquely match {requirement.package}.')
        package = packages.get(requirement.package, {})
        version_status = 'not_constrained'
        if requirement.version_major is not None:
            versions = package.get('records', [])
            if package.get('status') != 'installed' or not versions:
                version_status = 'unknown'
                reasons.append('Installed package version is unknown.')
            else:
                majors = [re.match(r'^([0-9]+)(?:\.|$)', r.get('version', '')) for r in versions]
                if any(match is None for match in majors):
                    version_status = 'unknown'
                    reasons.append('Package version is not a recognized numeric major.')
                elif any(int(match.group(1)) != requirement.version_major for match in majors):
                    version_status = 'mismatch'
                    reasons.append(f'Recipe requires package major version {requirement.version_major}.')
                else:
                    version_status = 'observed'
            if version_status in ('unknown', 'mismatch') and status == 'observed':
                status = version_status
        findings.append({'executable': requirement.executable, 'role': requirement.role,
                         'package': requirement.package, 'required_major': requirement.version_major,
                         'path': command.get('path') if command else None, 'status': status,
                         'version_status': version_status, 'reasons': reasons})
    return {'status': 'unverified', 'findings': findings,
            'notice': 'Observed requirements do not validate compatibility, provenance or safe reuse.'}
