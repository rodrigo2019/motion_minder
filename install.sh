#!/bin/bash

KLIPPER_PATH="${HOME}/klipper"
MOTION_MINDER_PATH="${HOME}/motion_minder"

set -eu
export LC_ALL=C

function preflight_checks {
  if [ "$EUID" -eq 0 ]; then
    echo "[PRE-CHECK] This script must not be run as root!"
    exit -1
  fi

  if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python 3 is not installed. Please install Python 3 to use the Motion Minder."
    exit -1
  fi

  if [ "$(sudo systemctl list-units --full -all -t service --no-legend | grep -F 'klipper.service')" ]; then
    printf "[PRE-CHECK] Klipper service found! Continuing...\n\n"
  else
    echo "[ERROR] Klipper service not found, please install Klipper first!"
    exit -1
  fi
}

function check_download {
  local motion_minderdirname motion_minderbasename
  motion_minderdirname="$(dirname "${MOTION_MINDER_PATH}")"
  motion_minderbasename="$(basename "${MOTION_MINDER_PATH}")"

  if [ ! -d "${MOTION_MINDER_PATH}" ]; then
    echo "[DOWNLOAD] Downloading Motion Minder repository..."
    if git -C "$motion_minderdirname" clone https://github.com/rodrigo2019/motion_minder.git "$motion_minderbasename"; then
      chmod +x "${MOTION_MINDER_PATH}"/install.sh
      printf "[DOWNLOAD] Download complete!\n\n"
    else
      echo "[ERROR] Download of Motion Minder git repository failed!"
      exit -1
    fi
  else
    printf "[DOWNLOAD] Motion Minder repository already found locally. Continuing...\n\n"
  fi
}

function link_extension {
  echo "[INSTALL] Linking scripts to your config directory..."
  ln -frsn "${MOTION_MINDER_PATH}"/motion_minder.py "${KLIPPER_PATH}"/klippy/extras/motion_minder.py
}

function restart_klipper {
  echo "[POST-INSTALL] Restarting Klipper..."
  sudo systemctl restart klipper
}

printf "\n=============================================\n"
echo "- Motion Minder module install script -"
printf "=============================================\n\n"

# Run steps
preflight_checks
check_download
link_extension
restart_klipper
