#!/usr/bin/env bash
# Removes what install.sh put in place. Your settings in ~/.config/goveehome are kept
# unless you pass --purge.
set -euo pipefail

APP_ID="io.github.vanquish1905.GoveeHome"
PREFIX="${PREFIX:-$HOME/.local}"

systemctl --user disable --now goveehome-sync.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/goveehome-sync.service"
rm -rf "$PREFIX/share/goveehome"
rm -f "$PREFIX/bin/goveehome" "$PREFIX/bin/goveehome-cli" \
      "$PREFIX/share/applications/$APP_ID.desktop" \
      "$PREFIX/share/metainfo/$APP_ID.metainfo.xml" \
      "$PREFIX/share/icons/hicolor/scalable/apps/$APP_ID.svg"
update-desktop-database -q "$PREFIX/share/applications" 2>/dev/null || true

if [ "${1:-}" = "--purge" ]; then
    rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/goveehome"
    echo "Removed GoveeHome and its settings."
else
    echo "Removed GoveeHome. Settings are still in ~/.config/goveehome (use --purge to delete them)."
fi
