Name:           desktopforge
Version:        0.1.0
Release:        0.1.dev%{?dist}
Summary:        Add Wayland compositor and shell sessions without replacing your desktop

License:        Apache-2.0
URL:            https://github.com/agentixsoftware/desktopforge
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  desktop-file-utils
BuildRequires:  systemd-rpm-macros
BuildRequires:  python3-pytest

Requires:       python3-pyside6

%description
DesktopForge inspects your system, shows which Wayland compositor and shell
combinations can be added as a separate login session, and previews exactly
what would change. It never replaces your existing desktop or display manager.
Installing requires the desktopforge-helper package and an approved recipe.

%package helper
Summary:        Privileged helper for DesktopForge (approved recipes only)
Requires:       %{name} = %{version}-%{release}
Requires:       python3-gobject-base
Requires:       polkit
Requires:       dnf5
Requires:       systemd
%{?systemd_requires}

%description helper
System D-Bus service that previews, installs, repairs and removes DesktopForge
login sessions from approved, bundled recipes only, after Polkit authorization.
It journals every step, records what it installed, and never runs arbitrary
commands or accepts recipe content from clients.

%prep
%autosetup -n %{name}-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files desktopforge
# The experimental nested trial launcher is not shipped; the login-session
# launcher below is a different program.
rm %{buildroot}%{_bindir}/desktopforge-session
install -Dm0755 packaging/desktopforge-helper %{buildroot}%{_libexecdir}/desktopforge/desktopforge-helper
install -Dm0755 src/desktopforge/loginsession.py %{buildroot}%{_libexecdir}/desktopforge/desktopforge-session
install -Dm0644 packaging/org.desktopforge.Helper1.conf %{buildroot}%{_datadir}/dbus-1/system.d/org.desktopforge.Helper1.conf
install -Dm0644 packaging/org.desktopforge.Helper1.service %{buildroot}%{_datadir}/dbus-1/system-services/org.desktopforge.Helper1.service
install -Dm0644 packaging/desktopforge-helper.service %{buildroot}%{_unitdir}/desktopforge-helper.service
install -Dm0644 packaging/org.desktopforge.policy %{buildroot}%{_datadir}/polkit-1/actions/org.desktopforge.policy
install -Dm0644 src/desktopforge/data/templates/niri-noctalia.kdl %{buildroot}%{_datadir}/desktopforge/templates/niri-noctalia.kdl
desktop-file-install --dir=%{buildroot}%{_datadir}/applications packaging/desktopforge.desktop
install -dm0755 %{buildroot}%{_sharedstatedir}/desktopforge/installs

%check
%pyproject_check_import -e 'desktopforge.gui*' -e 'desktopforge.helperd*'
%pytest -q tests/test_helper_core.py tests/test_helper_pkgtx.py tests/test_install_records.py tests/test_removal.py tests/test_repair.py tests/test_rendering.py tests/test_loginsession.py tests/test_helper_profiles.py

%post helper
%systemd_post desktopforge-helper.service

%preun helper
%systemd_preun desktopforge-helper.service

%postun helper
%systemd_postun desktopforge-helper.service

%files -f %{pyproject_files}
%license LICENSE
%doc README.md
%{_bindir}/desktopforge
%{_bindir}/desktopforge-gui
%{_datadir}/applications/desktopforge.desktop

%files helper
%dir %{_libexecdir}/desktopforge
%{_libexecdir}/desktopforge/desktopforge-helper
%{_libexecdir}/desktopforge/desktopforge-session
%{_datadir}/dbus-1/system.d/org.desktopforge.Helper1.conf
%{_datadir}/dbus-1/system-services/org.desktopforge.Helper1.service
%{_unitdir}/desktopforge-helper.service
%{_datadir}/polkit-1/actions/org.desktopforge.policy
%{_datadir}/desktopforge/
%dir %{_sharedstatedir}/desktopforge
%dir %{_sharedstatedir}/desktopforge/installs

%changelog
* Sun Nov 15 2026 Vick Reddy <agentixsoftware@gmail.com> - 0.1.0-0.1.dev
- Development build: helper with production profile, no approved recipes yet
