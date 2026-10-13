#!/usr/bin/env bash
# Install Kestrel for the current user (no root needed except for pacman deps).
#   ./install.sh            install / update
#   ./install.sh --default  also make Kestrel the default browser
#   ./install.sh --uninstall
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
app_dir="${XDG_DATA_HOME:-$HOME/.local/share}/kestrel-app"
bin="$HOME/.local/bin/kestrel"
desktop="${XDG_DATA_HOME:-$HOME/.local/share}/applications/kestrel.desktop"
icon="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/kestrel.svg"

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -rf "$app_dir" "$bin" "$desktop" "$icon"
  echo "Kestrel removed (history/bookmarks kept in ~/.local/share/kestrel)."
  exit 0
fi

if command -v pacman >/dev/null; then
  missing=()
  for p in python-pyqt6 python-pyqt6-webengine qt6-wayland; do
    pacman -Qi "$p" >/dev/null 2>&1 || missing+=("$p")
  done
  if ((${#missing[@]})); then
    echo ":: installing ${missing[*]}"
    sudo pacman -S --needed --noconfirm "${missing[@]}"
  fi
fi

mkdir -p "$app_dir" "$(dirname "$bin")" "$(dirname "$desktop")" "$(dirname "$icon")"
rm -rf "$app_dir/kestrel"
cp -r "$here/kestrel" "$app_dir/"
cat > "$bin" <<LAUNCH
#!/bin/sh
PYTHONPATH="$app_dir\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m kestrel "\$@"
LAUNCH
chmod +x "$bin"
sed "s|^Exec=kestrel|Exec=$bin|" "$here/packaging/kestrel.desktop" > "$desktop"
cp "$here/packaging/kestrel.svg" "$icon"
command -v update-desktop-database >/dev/null && update-desktop-database -q "$(dirname "$desktop")" || true

cfg="${XDG_CONFIG_HOME:-$HOME/.config}/kestrel/config.toml"
if [[ ! -f "$cfg" ]]; then
  mkdir -p "$(dirname "$cfg")"
  cp "$here/config.example.toml" "$cfg"
  echo ":: wrote example config to $cfg"
fi

if [[ "${1:-}" == "--default" ]]; then
  xdg-settings set default-web-browser kestrel.desktop
  xdg-mime default kestrel.desktop x-scheme-handler/http x-scheme-handler/https text/html
  echo ":: Kestrel is now the default browser (Super+Shift+B in Omarchy opens it)"
fi

echo "Kestrel installed. Run 'kestrel' or launch it from the Omarchy menu (Super+Space). Press F1 inside for shortcuts."
