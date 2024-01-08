#!/usr/bin/env bash

source ~/motion_minder-env/bin/activate
python ~/motion_minder/motion_minder/motion_minder.py "$@"
deactivate
