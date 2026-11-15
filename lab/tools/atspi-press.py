"""Agent lab tool (run inside the guest user session): atspi-press.py [--list | NAME...]: list or press DesktopForge buttons by accessible name (guest user session)."""
import sys, time
import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

def walk(node, depth=0):
    if node is None or depth > 25:
        return
    yield node
    for i in range(node.get_child_count()):
        yield from walk(node.get_child_at_index(i), depth + 1)

def app():
    desktop = Atspi.get_desktop(0)
    for i in range(desktop.get_child_count()):
        a = desktop.get_child_at_index(i)
        for n in walk(a):
            try:
                if n.get_role_name() == 'frame' and (n.get_name() or '').startswith('DesktopForge — Desktop session planner'):
                    return a
            except Exception:
                pass
    return None

target = app()
if target is None:
    sys.exit('DesktopForge window not found on AT-SPI')
buttons = [n for n in walk(target) if n.get_role_name() in ('push button', 'button')]
if sys.argv[1:] == ['--list']:
    for b in buttons:
        print(repr(b.get_name()), 'enabled' if b.get_state_set().contains(Atspi.StateType.ENABLED) else 'disabled')
    sys.exit(0)
for name in sys.argv[1:]:
    match = [b for b in walk(target) if b.get_role_name() in ('push button', 'button') and b.get_name() == name]
    if not match or not match[0].get_state_set().contains(Atspi.StateType.ENABLED):
        sys.exit(f'button {name!r} not found or disabled')
    match[0].get_action_iface().do_action(0)
    print(f'pressed {name!r}')
    time.sleep(1)
