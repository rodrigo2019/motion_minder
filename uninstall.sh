#!/bin/bash

KLIPPER_PATH="${HOME}/klipper"
MOTION_MINDER_PATH="${HOME}/motion_minder"

set -eu
export LC_ALL=C

function pre_uninstall_checks {
  if [ "$EUID" -eq 0 ]; then
    echo "[PRE-CHECK] This script must not be run as root!"
    exit -1
  fi

  if [ ! -d "${MOTION_MINDER_PATH}" ]; then
    echo "[ERROR] Motion Minder repository not found locally. Cannot proceed with uninstall."
    exit -1
  fi
}

function unlink_extension {
  echo "[UNINSTALL] Unlinking Motion Minder scripts from your config directory..."
  if [ -L "${KLIPPER_PATH}/klippy/extras/motion_minder.py" ]; then
    rm -f "${KLIPPER_PATH}/klippy/extras/motion_minder.py"
    echo "[UNINSTALL] Link removed successfully."
  else
    echo "[WARNING] Link does not exist or has already been removed."
  fi
}

function remove_repository {
  echo "[UNINSTALL] Removing Motion Minder repository..."
  rm -rf "${MOTION_MINDER_PATH}"
  echo "[UNINSTALL] Motion Minder repository removed successfully."
}

function restart_klipper {
  echo "[POST-UNINSTALL] Restarting Klipper..."
  sudo systemctl restart klipper
}

printf "\n=================================================\n"
echo "- Motion Minder module uninstall script -"
printf "=================================================\n\n"

# Run steps
pre_uninstall_checks
unlink_extension
remove_repository
restart_klipper

echo "Motion Minder module has been successfully uninstalled. Remove the motion_minder section from your printer.cfg file."
echo "Remember to check for and manually delete the database if desired."
echo "The database is located default at: ${HOME}/printer_data/data_base/motion_minder.*"
