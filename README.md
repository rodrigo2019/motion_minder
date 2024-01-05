# motionminder
Motion tracking for rails maintenance.


## Installation

Follow these steps to install the Shake&Tune module in your printer:
  1. Then, you can install the Shake&Tune package by running over SSH on your printer:
     ```bash
     wget -O - https://raw.githubusercontent.com/rodrigo2019/motion_minder/main/install.sh | bash
     ```
  1. Finally, append the following to your `printer.cfg` file and restart Klipper (if prefered, you can include only the needed macros: using `*.cfg` is a convenient way to include them all at once):
     ```
     [include motion_minder/*.cfg]
     ```
  1. Optionally, if you want to get automatic updates, add the following to your `moonraker.cfg` file:
     ```
     [update_manager MotionMinder]
     type: git_repo
     path: ~/motion_minder
     channel: beta
     origin: https://github.com/rodrigo2019/motion_minder.git
     primary_branch: main
     managed_services: klipper
     install_script: install.sh
     ```