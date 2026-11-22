Name:           goveehome
Version:        1.8.3
Release:        1%{?dist}
Summary:        Control Govee lights on Linux and sync them with your screen

License:        EPL-2.0
URL:            https://github.com/Vanquish1905/GoveeHome-For-Linux
Source0:        GoveeHome-For-Linux-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib

Requires:       python3-gobject
Requires:       python3-cairo
Requires:       python3-numpy
Requires:       python3-pillow
Requires:       gtk4
Requires:       libadwaita >= 1.4
Requires:       gstreamer1-plugins-base
Requires:       gstreamer1-plugins-good
Requires:       pipewire-gstreamer
Recommends:     python3-mss
Recommends:     python3-bleak

%description
A desktop app for Govee LED strips, TV backlights, lamps and bulbs. Lights are
found on the local network and controlled over the Govee LAN API. Screen sync
makes them follow the colours on your screen, on Wayland and X11.

%prep
%autosetup -n GoveeHome-For-Linux-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files goveehome
install -Dm644 data/io.github.vanquish1905.GoveeHome.desktop \
    %{buildroot}%{_datadir}/applications/io.github.vanquish1905.GoveeHome.desktop
install -Dm644 data/io.github.vanquish1905.GoveeHome.metainfo.xml \
    %{buildroot}%{_metainfodir}/io.github.vanquish1905.GoveeHome.metainfo.xml
install -Dm644 data/icons/io.github.vanquish1905.GoveeHome.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/io.github.vanquish1905.GoveeHome.svg
install -Dm644 packaging/systemd/goveehome-sync.service \
    %{buildroot}%{_userunitdir}/goveehome-sync.service
sed -i 's|%%h/.local/bin/goveehome-cli|%{_bindir}/goveehome-cli|' \
    %{buildroot}%{_userunitdir}/goveehome-sync.service

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/*.desktop
appstream-util validate-relax --nonet %{buildroot}%{_metainfodir}/*.metainfo.xml

%files -f %{pyproject_files}
%license LICENSE
%doc README.md SETUP.md
%{_bindir}/goveehome
%{_bindir}/goveehome-cli
%{_datadir}/applications/io.github.vanquish1905.GoveeHome.desktop
%{_metainfodir}/io.github.vanquish1905.GoveeHome.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/io.github.vanquish1905.GoveeHome.svg
%{_userunitdir}/goveehome-sync.service

%changelog
* Sun Nov 22 2026 vanquish1905 <vanquish.16.3.1905@gmail.com> - 1.8.3-1
- Colour strength for screen sync, slow effects, music feel and sensitivity
* Sun Nov 22 2026 vanquish1905 <vanquish.16.3.1905@gmail.com> - 1.8.2-1
- Screen sync style ported from GoveeScreen, now the default
* Sun Nov 22 2026 vanquish1905 <vanquish.16.3.1905@gmail.com> - 1.8.1-1
- Check and fix swapped capture colours
* Sat Nov 21 2026 vanquish1905 <vanquish.16.3.1905@gmail.com> - 1.8.0-1
- Colour test per light, streaming only assumed where known to work
* Sat Nov 21 2026 vanquish1905 <vanquish.16.3.1905@gmail.com> - 1.7.0-1
- Vividness for screen sync, fixes white output on RGBWW lights
* Sat Nov 21 2026 vanquish1905 <vanquish.16.3.1905@gmail.com> - 1.6.0-1
- KDE capture fixes, colour boost, diagnostics, 35 more effects
* Sat Nov 21 2026 vanquish1905 <vanquish.16.3.1905@gmail.com> - 1.5.0-1
- Strongest-colour pick for screen sync, 30 animated effects with previews
* Sat Nov 21 2026 vanquish1905 <vanquish.16.3.1905@gmail.com> - 1.4.0-1
- Screen sync follows videos in windows and ignores white areas
* Sat Nov 21 2026 vanquish1905 <vanquish.16.3.1905@gmail.com> - 1.3.0-1
- Faster capture without flashing, light bar layouts, more effects and palettes
* Sat Nov 21 2026 vanquish1905 <vanquish.16.3.1905@gmail.com> - 1.2.0-1
- Built-in updater
* Sat Nov 21 2026 vanquish1905 <vanquish.16.3.1905@gmail.com> - 1.1.0-1
- Accurate, faster screen sync; music sync; effects; groups; colour correction
* Sat Nov 21 2026 vanquish1905 <vanquish.16.3.1905@gmail.com> - 1.0.0-1
- First release
