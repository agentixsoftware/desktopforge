"""Cold VM disk backups must be verified, non-destructive and refuse live disks."""
import json
from pathlib import Path
import runpy

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/desktopforge-vm'


@pytest.fixture
def vm(tmp_path):
    namespace = runpy.run_path(str(SCRIPT))
    globals_ = namespace['backup'].__globals__
    root = tmp_path / 'lab'
    run = root / 'run-kvm'
    run.mkdir(parents=True)
    (run / 'guest.qcow2').write_bytes(b'baseline disk')
    globals_.update(ROOT=root, RUN=run, USE_TLS=True)

    def stopped(*_args, **_kwargs):
        raise ConnectionRefusedError
    globals_['qmp'] = stopped
    return namespace, globals_, run


def test_backup_and_restore_round_trip(vm, capsys):
    ns, _, run = vm
    ns['backup']('clean')
    record = json.loads((run.parent / 'backups-kvm/clean.json').read_text())
    assert record['profile'] == 'kvm' and record['size'] == len(b'baseline disk')
    (run / 'guest.qcow2').write_bytes(b'mutated by an install test')
    ns['restore']('clean')
    assert (run / 'guest.qcow2').read_bytes() == b'baseline disk'
    assert not (run / 'guest.qcow2.restore').exists()
    ns['list_backups']()
    assert '"name": "clean"' in capsys.readouterr().out


def test_refuses_to_copy_or_replace_a_running_disk(vm):
    ns, globals_, run = vm
    ns['backup']('clean')
    globals_['qmp'] = lambda *a, **k: {'status': 'running'}
    with pytest.raises(RuntimeError, match='Stop the VM'):
        ns['backup']('other')
    (run / 'guest.qcow2').write_bytes(b'live')
    with pytest.raises(RuntimeError, match='Stop the VM'):
        ns['restore']('clean')
    assert (run / 'guest.qcow2').read_bytes() == b'live'


def test_existing_backup_is_never_overwritten(vm):
    ns, _, run = vm
    ns['backup']('clean')
    (run / 'guest.qcow2').write_bytes(b'changed')
    with pytest.raises(RuntimeError, match='already exists'):
        ns['backup']('clean')
    assert (run.parent / 'backups-kvm/clean.qcow2').read_bytes() == b'baseline disk'


def test_corrupt_backup_does_not_touch_working_disk(vm):
    ns, _, run = vm
    ns['backup']('clean')
    (run.parent / 'backups-kvm/clean.qcow2').write_bytes(b'bit rot')
    (run / 'guest.qcow2').write_bytes(b'current')
    with pytest.raises(RuntimeError, match='recorded hash'):
        ns['restore']('clean')
    assert (run / 'guest.qcow2').read_bytes() == b'current'


@pytest.mark.parametrize('name', ['', '../escape', 'a/b', 'UPPER', '-flag', '.hidden', 'x' * 65])
def test_backup_names_cannot_escape_or_inject(vm, name):
    ns, _, _ = vm
    with pytest.raises(ValueError):
        ns['backup_paths'](name)


def test_backup_directory_symlink_is_refused(vm, tmp_path):
    ns, _, run = vm
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    (run.parent / 'backups-kvm').symlink_to(elsewhere)
    with pytest.raises(RuntimeError, match='not owned'):
        ns['backup']('clean')
    assert list(elsewhere.iterdir()) == []


def test_guest_reboot_is_not_turned_into_qemu_exit():
    assert '-no-reboot' not in SCRIPT.read_text()


@pytest.mark.parametrize('show, gl, device, display', [
    (False, False, 'virtio-vga', 'none'),
    (True, False, 'virtio-vga', 'gtk,gl=off'),
    (True, True, 'virtio-vga-gl', 'gtk,gl=on'),
    (False, True, 'virtio-vga-gl', 'egl-headless'),
])
def test_qemu_display_modes(vm, show, gl, device, display):
    ns, _, run = vm
    args = ns['qemu_args']('kvm', show, gl, 4321)
    assert args[args.index('-display') + 1] == display
    devices = [args[i + 1] for i, a in enumerate(args) if a == '-device']
    assert device in devices and len([d for d in devices if d.startswith('virtio-vga')]) == 1
    assert f'file={run}/guest.qcow2,format=qcow2,if=virtio' in args and '-no-reboot' not in args
    assert 'tls-creds=console-tls' in ' '.join(args)  # kvm profile keeps the authenticated console
