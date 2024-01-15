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
## Usage

The motion minder is designed to be as unobtrusive as possible. It will automatically start tracking your printer's 
movements as soon as it's installed. You can check the and set the motion minder by running the following 
commands over your favorite printer console client (e.g. Fluidd, Mainsail, etc.):

First of all, set when will be your next maintenance:

```bash
MOTION_MINDER NEXT_MAINTENANCE=100
```

Then, you can check the current status of the motion minder:

```bash
MOTION_MINDER STATS=TRUE
```

If you need, you can reset the odometer to a desired value:

```bash
MOTION_MINDER SET_AXIS=10 AXIS=X
```

As a experimental feature, you can also process your printer history, its necessary to have all the G-code files in the 
gcodes folder, then you can run the following command:

It can take a while, depending on the number of files, so be patient.
```bash
MOTION_MINDER PROCESS_HISTORY=TRUE
```

## Macro arguments

The following arguments can be used to customize the behavior of the motion minder:

| Argument           | Default | Description                                                                                                    |
|--------------------|---------|----------------------------------------------------------------------------------------------------------------|
| `NEXT_MAINTENANCE` | None    | The distance (in km) to the next maintenance. it can be used with `AXES` to specify which axis you want to set |
| `SET_AXIS`         | None    | A value to set the odometer. It can be used with `AXES` to specify which axis you want to set                  |
| `STATS`            | None    | If set to `TRUE`, it will print the current status of the motion minder                                         |
| `PROCESS_HISTORY`  | None    | If set to `TRUE`, it will process all the G-code files in the gcodes folder                                     |
| `AXES`             | "xyz"   | The axis to be used with `NEXT_MAINTENANCE` and `SET_AXES`                                                     |