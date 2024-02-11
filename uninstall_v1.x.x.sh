#!/bin/bash
# This script uninstall MotionMinder
set -eu

SYSTEMDDIR="/etc/systemd/system"
MOTION_MINDER_ENV="${HOME}/motion_minder-env"
MOTION_MINDER_DIR="${HOME}/motion_minder"

remove_all(){
  echo -e "Stopping services"

  services_list=($(sudo systemctl list-units -t service --full | grep MotionMinder | awk '{print $1}'))
  echo -e "${services_list[@]}"
  for service in "${services_list[@]}"
  do
    echo -e "${service}"
    echo -e "Removing $service ..."
    sudo systemctl stop $service
    sudo systemctl disable $service
    sudo rm -f $SYSTEMDDIR/$service
    echo -e "Done!"
  done

  rm -rf "${HOME}/printer_data/logs/motion_minder*"


  sudo systemctl daemon-reload
  sudo systemctl reset-failed

  ### remove MotionMinder dir
  if [ -d "$MOTION_MINDER_ENV" ]; then
    echo -e "Removing MotionMinder VENV directory ..."
    rm -rf "${MOTION_MINDER_ENV}" && echo -e "Directory removed!"
  fi

  if [ -d "$MOTION_MINDER_DIR" ]; then
    echo -e "Removing MotionMinder directory ..."
    rm -rf "${MOTION_MINDER_DIR}" && echo -e "Directory removed!"
  fi
}

delete_db(){
  echo -e "Removing MotionMinder database from moonraker ..."
  "${MOTION_MINDER_ENV}"/bin/python "${MOTION_MINDER_DIR}"/scripts/delete_db.py
}

delete_db
remove_all