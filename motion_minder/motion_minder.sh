#!/usr/bin/env bash

source ~/motion_minder-env/bin/activate
python ~/printer_data/config/motion_minder/motion_minder.py "$@"
deactivate
