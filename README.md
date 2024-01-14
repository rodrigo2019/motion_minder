# MotionMinder

Motion tracking for rails maintenance. Instead of relying solely on time, let's throw in some mileage, just like we do with cars. Time to see how many 'prints per kilometer' your trusty printer has got under its belt!

## How it works

It operates in two modes, automatically selected based on the current state of the printer:

  1. **Idle**: During this mode, the motion minder relies on tracking the carriage position through the live_motion object provided by Moonraker. It's important to note that this mode may have some limitations in terms of accuracy. This is primarily due to the time-sliced updates received from the websocket. As a result, small, high-speed movements may not be reliably detected, or the system might only capture partial movement.
  1. **Printing**: In this state, movements are monitored based on the instructions within the G-code file. Specifically, the system focuses on tracking G1 and G0 commands, while Klipper macros and commands like `QUAD_GANTRY_LEVEL`, `Z_TILT_ADJUST`, `BED_MESH_CALIBRATE` and `G28` cannot be feasibly tracked in this mode.

## Installation

Follow these steps to install the Motion Minder in your printer:

  1. Then, you can install the package by running over SSH on your printer:

     ```bash
     wget -O - https://raw.githubusercontent.com/rodrigo2019/motion_minder/main/install.sh | bash
     ```

  1. Finally, append the following to your `printer.cfg` file and restart Klipper (if prefered, you can include only the needed macros: using `*.cfg` is a convenient way to include them all at once):

     ```ini
     [include motion_minder/*.cfg]
     ```

  1. Optionally, if you want to get automatic updates, add the following to your `moonraker.cfg` file:

     ```ini
     [update_manager MotionMinder]
     type: git_repo
     path: ~/motion_minder
     channel: dev
     origin: https://github.com/rodrigo2019/motion_minder.git
     primary_branch: main
     install_script: install.sh
     ```
