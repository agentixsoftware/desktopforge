"""Unprivileged client for the VM-lab helper (org.desktopforge.LabHelper1).

Used by the GUI's lab mode and the lab command-line client. It only previews
and requests apply; authorization is Polkit's, decisions are the helper's.
PyGObject is imported lazily so the read-only core never depends on it.

One private bus connection is kept for preview and apply, because approval
tokens are bound to the connection that previewed.
"""

BUS_NAME = 'org.desktopforge.LabHelper1'
OBJECT_PATH = '/org/desktopforge/LabHelper1'
INTERFACE = BUS_NAME
APPLY_TIMEOUT_MS = 20 * 60 * 1000

# GUI combinations the lab helper can install. Nothing else is offered.
LAB_RECIPES = {('niri', 'noctalia'): 'fedora45-niri-noctalia-lab'}
REMOVAL_PREFIX = 'remove-'
REPAIR_PREFIX = 'repair-'
REPAIRABLE = ('modified', 'incomplete')


def repair_action(plan: dict | None, available: bool) -> str | None:
    """repair-<install_id> for a damaged recorded installation in lab mode, else None."""
    existing = (plan or {}).get('existing_installation')
    if available and existing and existing.get('status') in REPAIRABLE:
        return REPAIR_PREFIX + existing['install_id']
    return None


def lab_action(plan: dict | None, available: bool) -> tuple[str, str] | None:
    """(kind, recipe_id) the GUI may offer for this plan in lab mode, or None.

    kind is 'install' or 'remove'. Removal is offered for a recorded installation
    that is not already removed; install only for combinations the helper has.
    """
    if not available or not plan:
        return None
    existing = plan.get('existing_installation')
    if existing and existing.get('status') not in ('removed',):
        return 'remove', REMOVAL_PREFIX + existing['install_id']
    target = plan.get('target') or {}
    recipe = LAB_RECIPES.get((target.get('compositor'), target.get('shell')))
    return ('install', recipe) if recipe else None


class LabHelperClient:
    def __init__(self):
        from gi.repository import Gio, GLib  # lazy: only the lab path needs PyGObject
        self.Gio, self.GLib = Gio, GLib
        address = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SYSTEM, None)
        self.bus = Gio.DBusConnection.new_for_address_sync(
            address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
            | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)

    @staticmethod
    def available() -> bool:
        """True when the lab helper is installed (activatable) on the system bus."""
        try:
            from gi.repository import Gio, GLib
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
            for method in ('ListActivatableNames', 'ListNames'):
                names = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                                      method, None, GLib.VariantType('(as)'), Gio.DBusCallFlags.NONE,
                                      3000, None).unpack()[0]
                if BUS_NAME in names:
                    return True
        except Exception:  # no PyGObject, no system bus, or any bus error: not available
            return False
        return False

    def _error(self, exc):
        name = self.Gio.DBusError.get_remote_error(exc)
        reason = exc.message.split(f'{name}: ', 1)[-1] if name else exc.message
        return {'ok': False, 'error': name, 'reason': reason}

    def preview(self, recipe_id: str) -> dict:
        try:
            reply = self.bus.call_sync(BUS_NAME, OBJECT_PATH, INTERFACE, 'Preview',
                                       self.GLib.Variant('(s)', (recipe_id,)), self.GLib.VariantType('(a{sv})'),
                                       self.Gio.DBusCallFlags.NONE, 120000, None)
            return {'ok': True, **reply.unpack()[0]}
        except self.GLib.Error as exc:
            return self._error(exc)

    def apply(self, token: str, plan_hash: str, progress=None) -> dict:
        """Request apply; progress(step, message) is called for each helper step."""
        Gio, GLib = self.Gio, self.GLib
        context = GLib.MainContext.new()
        context.push_thread_default()
        loop, outcome = GLib.MainLoop.new(context, False), {}
        try:
            def on_progress(_conn, _sender, _path, _iface, _signal, params):
                if progress:
                    progress(*params.unpack())
            watch = self.bus.signal_subscribe(None, INTERFACE, 'Progress', OBJECT_PATH, None,
                                              Gio.DBusSignalFlags.NONE, on_progress)

            def done(connection, result):
                try:
                    outcome.update({'ok': True, **connection.call_finish(result).unpack()[0]})
                except GLib.Error as exc:
                    outcome.update(self._error(exc))
                loop.quit()
            self.bus.call(BUS_NAME, OBJECT_PATH, INTERFACE, 'Apply', GLib.Variant('(ss)', (token, plan_hash)),
                          GLib.VariantType('(a{sv})'), Gio.DBusCallFlags.NONE, APPLY_TIMEOUT_MS, None, done)
            loop.run()
            self.bus.signal_unsubscribe(watch)
        finally:
            context.pop_thread_default()
        return outcome
