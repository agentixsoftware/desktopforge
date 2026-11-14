from desktopforge.session_analysis import inspect_processes


def test_process_names_are_exact_and_arguments_are_not_evidence(tmp_path):
    for pid, executable in enumerate(['ryoku-shell', 'not-ryoku', 'bash', 'niri', 'Hyprland'], 1):
        directory = tmp_path / str(pid)
        directory.mkdir()
        (directory / 'cmdline').write_bytes(executable.encode() + b'\0ryoku\0')
        (directory / 'cgroup').write_text('0::/example')
    result = inspect_processes(tmp_path)
    assert [p['pid'] for p in result] == [1, 4, 5]
    assert result[0]['shell_candidates'] == ['ryoku']


def test_missing_proc_is_graceful(tmp_path):
    assert inspect_processes(tmp_path / 'missing') == []
