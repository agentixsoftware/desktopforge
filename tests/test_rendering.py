"""Rendering preflight: probe classification, isolation, and planner/GUI integration."""
import json
import subprocess

import pytest

from desktopforge import rendering
from desktopforge.helper import gpuprobe


@pytest.mark.parametrize('device_software, renderer, expected', [
    (False, 'virgl (Mesa Intel(R) Iris(R) Xe Graphics (ADL GT2))', 'hardware'),
    (False, 'AMD Radeon Graphics (radeonsi, renoir)', 'hardware'),
    (True, 'llvmpipe (LLVM 21.1.0, 256 bits)', 'software'),
    (False, 'llvmpipe (LLVM 21.1.0, 256 bits)', 'software'),   # either signal is enough
    (True, None, 'software'),
    (None, 'Mesa Intel(R) Iris(R) Xe Graphics', 'unknown'),     # device class not confirmed
    (False, None, 'unknown'),
])
def test_classification(device_software, renderer, expected):
    assert gpuprobe.classify(device_software, renderer) == expected


@pytest.mark.parametrize('classes, expected', [
    ([], 'none'), (['software'], 'software-only'), (['software', 'hardware'], 'hardware'),
    (['unknown'], 'unknown'), (['software', 'unknown'], 'unknown'),
])
def test_summary(classes, expected):
    assert gpuprobe.summarize([{'renderer_class': c} for c in classes]) == expected


class Run:
    def __init__(self, returncode=0, stdout='', exc=None):
        self.returncode, self.stdout, self.exc, self.calls = returncode, stdout, exc, []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, '')


SOFTWARE = json.dumps({'schema_version': 1, 'status': 'software-only', 'nodes': [
    {'node': '/dev/dri/renderD128', 'renderer': 'llvmpipe (LLVM 21.1.0, 256 bits)',
     'renderer_class': 'software', 'device_software': True}]})


def test_probe_runs_isolated_with_a_clean_environment():
    run = Run(stdout=SOFTWARE)
    result = rendering.inspect_rendering(runner=run)
    argv, kwargs = run.calls[0]
    assert argv[1:] == ['-I', str(rendering.PROBE)]
    assert kwargs['env'] == rendering.CLEAN_ENV and 'LIBGL_ALWAYS_SOFTWARE' not in kwargs['env']
    assert kwargs['timeout'] == 15
    assert result['status'] == 'software-only' and result['nodes'][0]['renderer'].startswith('llvmpipe')


@pytest.mark.parametrize('run', [
    Run(returncode=-11), Run(stdout='not json'), Run(stdout=json.dumps({'schema_version': 1, 'status': 'great'})),
    Run(exc=subprocess.TimeoutExpired('probe', 15)), Run(exc=OSError('no python')),
])
def test_probe_failures_are_unknown_not_hardware(run):
    assert rendering.inspect_rendering(runner=run)['status'] == 'unknown'


def test_fixture_roots_are_not_probed(tmp_path):
    assert rendering.inspect_rendering(tmp_path)['status'] == 'unknown'


@pytest.mark.parametrize('status, fragment', [
    ('software-only', 'only offers software rendering (llvmpipe'),
    ('none', 'none was found'),
    ('unknown', 'could not be confirmed'),
])
def test_niri_is_blocked_without_confirmed_hardware(status, fragment):
    info = {'status': status, 'nodes': json.loads(SOFTWARE)['nodes'] if status == 'software-only' else []}
    assert fragment in rendering.rendering_blocker(info, 'niri')


def test_hardware_and_other_compositors_are_not_blocked():
    assert rendering.rendering_blocker({'status': 'hardware'}, 'niri') is None
    assert rendering.rendering_blocker({'status': 'software-only'}, 'hyprland') is None  # not verified; no claim


def test_planner_reports_the_rendering_blocker(tmp_path):
    from desktopforge.detection import detect_system
    from desktopforge.planning import build_plan
    inventory = detect_system(root=tmp_path, environ={}, which=lambda _: None)
    inventory['rendering'] = {'status': 'software-only', 'nodes': json.loads(SOFTWARE)['nodes']}
    assert any('software rendering' in b for b in build_plan(inventory, 'niri', 'noctalia')['blockers'])
    inventory['rendering'] = {'status': 'hardware', 'nodes': []}
    assert not any('graphics' in b for b in build_plan(inventory, 'niri', 'noctalia')['blockers'])


def test_probe_script_is_self_contained():
    import ast
    tree = ast.parse(rendering.PROBE.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module == 'ctypes' and node.level == 0
