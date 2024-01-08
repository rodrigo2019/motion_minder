#!/bin/bash

SYSTEMDDIR="/etc/systemd/system"
MOTION_MINDER_SERVICE="MotionMinder.service"
USER_CONFIG_PATH="${HOME}/printer_data/config"
KLIPPER_PATH="${HOME}/klipper"
MOONRAKER_MANAGED_SERVICES_FILE="${HOME}/printer_data/moonraker.asvc"

MOTION_MINDER_PATH="${HOME}/motion_minder"
MOTION_MINDER_VENV_PATH="${HOME}/motion_minder-env"

set -eu
export LC_ALL=C


function preflight_checks {
    if [ "$EUID" -eq 0 ]; then
        echo "[PRE-CHECK] This script must not be run as root!"
        exit -1
    fi

    if ! command -v python3 &> /dev/null; then
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
    motion_minderdirname="$(dirname ${MOTION_MINDER_PATH})"
    motion_minderbasename="$(basename ${MOTION_MINDER_PATH})"

    if [ ! -d "${MOTION_MINDER_PATH}" ]; then
        echo "[DOWNLOAD] Downloading Motion Minder repository..."
        if git -C $motion_minderdirname clone https://github.com/rodrigo2019/motion_minder.git $motion_minderbasename; then
            chmod +x ${MOTION_MINDER_PATH}/install.sh
            printf "[DOWNLOAD] Download complete!\n\n"
        else
            echo "[ERROR] Download of Motion Minder git repository failed!"
            exit -1
        fi
    else
        printf "[DOWNLOAD] Motion Minder repository already found locally. Continuing...\n\n"
    fi
}

function setup_venv {
    if [ ! -d "${MOTION_MINDER_VENV_PATH}" ]; then
        echo "[SETUP] Creating Python virtual environment..."
        virtualenv -p /usr/bin/python3 "${MOTION_MINDER_VENV_PATH}"
    else
        echo "[SETUP] Virtual environment already exists. Continuing..."
    fi

    source "${MOTION_MINDER_VENV_PATH}/bin/activate"
    echo "[SETUP] Installing/Updating Motion Minder dependencies..."
    pip install --upgrade pip
    pip install -r "${MOTION_MINDER_PATH}/requirements.txt"
    deactivate
    printf "\n"
}

function link_extension {
    echo "[INSTALL] Linking scripts to your config directory..."

    ln -frsn ${MOTION_MINDER_PATH}/motion_minder ${USER_CONFIG_PATH}/motion_minder
}

function link_gcodeshellcommandpy {
    if [ ! -f "${KLIPPER_PATH}/klippy/extras/gcode_shell_command.py" ]; then
        echo "[INSTALL] Downloading gcode_shell_command.py Klipper extension needed for this module"
        wget -P ${KLIPPER_PATH}/klippy/extras https://raw.githubusercontent.com/Frix-x/klippain/main/scripts/gcode_shell_command.py
    else
        printf "[INSTALL] gcode_shell_command.py Klipper extension is already installed. Continuing...\n\n"
    fi
}

create_service() {
  ### create systemd service file
  sudo /bin/sh -c "cat > ${SYSTEMDDIR}/${MOTION_MINDER_SERVICE}" <<EOF
#Systemd service file for Motion Minder
[Unit]
Description=Starts Motion Minder on startup
After=network-online.target moonraker.service

[Install]
WantedBy=multi-user.target

[Service]
Type=simple
User=${USER}
ExecStart=${MOTION_MINDER_VENV_PATH}/bin/python ${MOTION_MINDER_PATH}/motion_minder/printer_odometer.py
Restart=always
RestartSec=5
EOF

  ### enable instance
  sudo systemctl enable ${MOTION_MINDER_SERVICE}
  printf "[INSTALL] ${MOTION_MINDER_SERVICE} instance created!\n"

  ### launching instance
  printf "[INSTALL] Launching MotionMinder instance ...\n"
  sudo systemctl start ${MOTION_MINDER_SERVICE}

  # Check if the string is already present in the file on a line by itself
  if grep -Fxq "MotionMinder" "${MOONRAKER_MANAGED_SERVICES_FILE}"; then
    printf "[INSTALL] MotionMinder already present in Moonraker managed services. Continuing...\n"
  else
    # If not present, add the string to the file as a new line
    echo "MotionMinder" >> "${MOONRAKER_MANAGED_SERVICES_FILE}"
    printf "[INSTALL] MotionMinder added to Moonraker managed services!\n"
fi
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
setup_venv
link_extension
link_gcodeshellcommandpy
create_service
restart_klipper