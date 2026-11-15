"""Run the rendering probe in a separate, time-limited process with a clean environment."""
import json
from pathlib import Path
import subprocess
import sys

PROBE = Path(__file__).resolve().parent / 'helper' / 'gpuprobe.py'
CLASSES = ('hardware', 'software', 'unknown')
STATUSES = ('hardware', 'software-only', 'none', 'unknown')
# Overrides such as LIBGL_ALWAYS_SOFTWARE or MESA_LOADER_DRIVER_OVERRIDE must not leak in.
CLEAN_ENV = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'MESA_SHADER_CACHE_DISABLE': 'true', 'HOME': '/nonexistent'}


def parse(text: str) -> dict:
    data = json.loads(text)
    if not isinstance(data, dict) or data.get('schema_version') != 1 or data.get('status') not in STATUSES:
        raise ValueError('unexpected probe output')
    nodes = []
    for node in data.get('nodes', [])[:8]:
        if not isinstance(node, dict) or node.get('renderer_class') not in CLASSES:
            raise ValueError('unexpected probe node')
        renderer = node.get('renderer')
        nodes.append({'node': str(node.get('node'))[:64],
                      'renderer': renderer[:200] if isinstance(renderer, str) else None,
                      'renderer_class': node['renderer_class'],
                      'device_software': node.get('device_software') if isinstance(node.get('device_software'), bool) else None})
    return {'status': data['status'], 'nodes': nodes}


def inspect_rendering(root: Path = Path('/'), runner=None, timeout: float = 15) -> dict:
    base = {'schema_version': 1, 'status': 'unknown', 'nodes': [],
            'limitations': ['A hardware renderer is necessary for Niri, not proof that a session will work.']}
    if root != Path('/') and runner is None:
        return {**base, 'reason': 'Rendering is only probed on the live system.'}
    run = runner or subprocess.run
    try:
        result = run([sys.executable, '-I', str(PROBE)], stdin=subprocess.DEVNULL, capture_output=True,
                     text=True, timeout=timeout, env=dict(CLEAN_ENV), cwd='/')
        if result.returncode != 0:
            return {**base, 'reason': f'Rendering probe failed (status {result.returncode}).'}
        return {**base, **parse(result.stdout)}
    except subprocess.TimeoutExpired:
        return {**base, 'reason': 'Rendering probe timed out.'}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {**base, 'reason': f'Rendering probe unavailable: {exc}'}


def renderer_summary(rendering: dict) -> str:
    names = [n['renderer'] for n in rendering.get('nodes', []) if n.get('renderer')]
    return ', '.join(names) or 'no renderer reported'


# Compositors verified to refuse software rendering (Niri: "software EGL renderers are skipped").
NEEDS_HARDWARE = frozenset({'niri'})


def rendering_blocker(rendering: dict | None, compositor: str) -> str | None:
    if compositor not in NEEDS_HARDWARE:
        return None
    status = (rendering or {}).get('status', 'unknown')
    if status == 'hardware':
        return None
    if status == 'software-only':
        return (f'{compositor.capitalize()} needs hardware-accelerated graphics, but this system only offers '
                f'software rendering ({renderer_summary(rendering)}). The session would show no picture.')
    if status == 'none':
        return f'{compositor.capitalize()} needs a GPU render device, and none was found.'
    return f'Hardware-accelerated graphics for {compositor.capitalize()} could not be confirmed.'
