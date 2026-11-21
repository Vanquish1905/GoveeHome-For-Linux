#!/usr/bin/env bash
# Installs GoveeHome for the current user (no root needed apart from the
# distribution packages). Run ./install.sh --help for options.
set -euo pipefail

APP_ID="io.github.vanquish1905.GoveeHome"
PREFIX="${PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/goveehome"
VENV="$APP_DIR/venv"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DEPS=1
OPEN_FIREWALL=ask

usage() {
    cat <<USAGE
Usage: ./install.sh [options]

  --no-deps          don't install distribution packages
  --firewall         open UDP port 4002 in firewalld without asking
  --no-firewall      never touch the firewall
  -h, --help         show this help

Installs into $PREFIX (override with PREFIX=/some/where ./install.sh).
USAGE
}

for arg in "$@"; do
    case "$arg" in
        --no-deps) INSTALL_DEPS=0 ;;
        --firewall) OPEN_FIREWALL=yes ;;
        --no-firewall) OPEN_FIREWALL=no ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; usage; exit 1 ;;
    esac
done

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }

install_deps() {
    if command -v dnf >/dev/null; then
        say "Installing packages with dnf"
        sudo dnf install -y python3 python3-pip python3-gobject python3-cairo python3-numpy \
            python3-pillow gtk4 libadwaita gstreamer1-plugins-base gstreamer1-plugins-good \
            pipewire-gstreamer
    elif command -v apt-get >/dev/null; then
        say "Installing packages with apt"
        sudo apt-get update
        sudo apt-get install -y python3 python3-venv python3-pip python3-gi python3-gi-cairo \
            python3-numpy python3-pil gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gstreamer-1.0 \
            gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-pulseaudio \
            gstreamer1.0-pipewire
    elif command -v pacman >/dev/null; then
        say "Installing packages with pacman"
        sudo pacman -S --needed --noconfirm python python-pip python-gobject python-cairo \
            python-numpy python-pillow gtk4 libadwaita gst-plugins-base gst-plugins-good \
            gst-plugin-pipewire
    elif command -v zypper >/dev/null; then
        say "Installing packages with zypper"
        sudo zypper install -y python3 python3-pip python3-gobject python3-gobject-cairo \
            python3-numpy python3-Pillow gtk4 libadwaita-1-0 typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 \
            gstreamer-plugins-base gstreamer-plugins-good gstreamer-plugin-pipewire
    else
        say "Unknown package manager, skipping system packages."
        echo "    Install PyGObject, GTK 4, libadwaita, numpy, Pillow and the GStreamer base, good"
        echo "    and PipeWire plugins yourself."
    fi
}

check_firewall() {
    command -v firewall-cmd >/dev/null || return 0
    firewall-cmd --state >/dev/null 2>&1 || return 0
    local zone
    zone="$(firewall-cmd --get-default-zone 2>/dev/null || echo public)"
    if firewall-cmd --zone="$zone" --query-port=4002/udp >/dev/null 2>&1; then
        return 0
    fi
    # Fedora Workstation's zone already allows 1025-65535
    if firewall-cmd --zone="$zone" --list-ports 2>/dev/null | grep -q '1025-65535/udp'; then
        return 0
    fi
    [ "$OPEN_FIREWALL" = no ] && return 0
    if [ "$OPEN_FIREWALL" = ask ]; then
        echo
        echo "The firewall zone '$zone' blocks UDP port 4002, where lights send their replies."
        read -r -p "Open it now? [Y/n] " answer
        case "${answer:-y}" in [Nn]*) echo "    Skipped. See SETUP.md if no lights show up."; return 0 ;; esac
    fi
    sudo firewall-cmd --zone="$zone" --add-port=4002/udp --permanent
    sudo firewall-cmd --reload
}

[ "$INSTALL_DEPS" = 1 ] && install_deps

python3 - <<'PY' || { echo "PyGObject with GTK 4 and libadwaita is missing, see SETUP.md" >&2; exit 1; }
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw
assert (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 4), "libadwaita 1.4 or newer is needed"
PY

say "Creating virtual environment in $VENV"
mkdir -p "$APP_DIR"
# system site packages so the distribution's PyGObject is used
python3 -m venv --system-site-packages --clear "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet "$SRC[x11,bluetooth]"

say "Installing launchers, desktop entry and icon"
mkdir -p "$PREFIX/bin" "$PREFIX/share/applications" "$PREFIX/share/metainfo" \
         "$PREFIX/share/icons/hicolor/scalable/apps"
ln -sf "$VENV/bin/goveehome" "$PREFIX/bin/goveehome"
ln -sf "$VENV/bin/goveehome-cli" "$PREFIX/bin/goveehome-cli"
sed "s|^Exec=goveehome$|Exec=$PREFIX/bin/goveehome|" "$SRC/data/$APP_ID.desktop" \
    > "$PREFIX/share/applications/$APP_ID.desktop"
install -m644 "$SRC/data/$APP_ID.metainfo.xml" "$PREFIX/share/metainfo/"
install -m644 "$SRC/data/icons/$APP_ID.svg" "$PREFIX/share/icons/hicolor/scalable/apps/"
update-desktop-database -q "$PREFIX/share/applications" 2>/dev/null || true
gtk-update-icon-cache -q -t "$PREFIX/share/icons/hicolor" 2>/dev/null || true

check_firewall

echo
say "Done. Start GoveeHome from your app menu, or run: goveehome"
case ":$PATH:" in
    *":$PREFIX/bin:"*) ;;
    *) echo "    Note: $PREFIX/bin is not on your PATH, the menu entry works regardless." ;;
esac
