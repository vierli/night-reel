#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT_FILE="$UNIT_DIR/nightreel.service"
DISPLAY_VALUE="${DISPLAY:-:0}"
WAYLAND_VALUE="${WAYLAND_DISPLAY:-wayland-0}"
RUNTIME_VALUE="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

if [[ "$PROJECT_DIR" == *" "* ]]; then
  echo "Please move Night Reel to a folder without spaces before installing."
  exit 1
fi

echo "Installing VLC, Python, and integrated DMX support..."
sudo apt-get update
sudo apt-get install -y vlc python3-venv

NEEDS_RELOGIN=0
if ! id -nG | tr ' ' '\n' | grep -qx dialout; then
  sudo usermod -aG dialout "$(id -un)"
  NEEDS_RELOGIN=1
fi

if systemctl list-unit-files --type=service | grep -q '^dmx-controller.service'; then
  echo "Disabling the separate DMX controller service; Night Reel now owns the UART..."
  sudo systemctl disable --now dmx-controller.service
fi

echo "Creating the Night Reel environment..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

mkdir -p "$UNIT_DIR"
sed \
  -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
  -e "s|__PYTHON__|$VENV_DIR/bin/python|g" \
  -e "s|__DISPLAY__|$DISPLAY_VALUE|g" \
  -e "s|__WAYLAND_DISPLAY__|$WAYLAND_VALUE|g" \
  -e "s|__XDG_RUNTIME_DIR__|$RUNTIME_VALUE|g" \
  "$PROJECT_DIR/deploy/nightreel.service.template" > "$UNIT_FILE"

systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable nightreel.service
systemctl --user restart nightreel.service

PI_IP="$(hostname -I | awk '{print $1}')"
echo
echo "Night Reel is running. Open http://${PI_IP:-raspberrypi.local}:8080"
echo "Service status: systemctl --user status nightreel"
if [[ "$NEEDS_RELOGIN" -eq 1 ]]; then
  echo "IMPORTANT: Reboot once so Night Reel receives permission to use /dev/ttyAMA0."
fi
