# MotionMinder

Motion tracking for rails maintenance. Instead of relying solely on time, let's throw in some mileage, just like we do
with cars. Time to see how many 'prints per kilometer' your trusty printer has got under its belt!

## How it works

It works as a module for Klipper, it will track the movements of your printer and will calculate the distance
traveled by each axis. It will also keep track of the total distance traveled by your printer, and will notify you
when it's time to do some maintenance.

It tracks the movements of your printer by decorating the `toolhead.move` method. Decorations are a way to add
functionality to existing methods. In this case, we are adding a function that will be called every time the
`toolhead.move` method is called.

## Installation

Follow these steps to install the Motion Minder in your printer:

1. Then, you can install the package by running over SSH on your printer:

   ```bash
   wget -O - https://raw.githubusercontent.com/rodrigo2019/motion_minder/main/install.sh | bash
   ```

1. Finally, append the following to your `printer.cfg` file and restart Klipper:

   ```ini
   [motion_minder]
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
   managed_services: klipper
   ```

## Usage

The motion minder kicks in automatically upon installation, tracking your printer's movements.
To check and configure it, use the following commands with your favorite printer console client
(e.g., Fluidd, Mainsail, etc.):

First of all, set when will be your next maintenance:

```bash
MOTION_MINDER SET_MAINTENANCE=100
```

doing this, the motion minder will notify you when the printer reaches 100km of movement.

Then, you can check the current status of the motion minder:

```bash
MOTION_MINDER
```

If you need, you can reset the odometer to a desired value:

```bash
MOTION_MINDER SET_ODOMETER=100 AXES=xy UNIT=mm
```

in the example above, the odometer will be set to 100km for the x and y axis.

Now, lets say you want to set the maintenance to 100km relative from your current odometer:

```bash
MOTION_MINDER SET_MAINTENANCE=100 RELATIVE=True
```

or 

```bash
 MOTION_MINDER SET_MAINTENANCE=100 RELATIVE=True AXES=xyz UNIT=km
```

## Module arguments

The following arguments can be used to customize the behavior of the motion minder:

| Argument          | Default | Description                                                                                                                                                                                                             |
|-------------------|---------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `SET_MAINTENANCE` | None    | A value to determine the remaining distance until the next maintenance. You can customize it using the `AXES` parameter to specify the desired axis and the `UNIT` parameter to set the measurement unit for the value. |
| `SET_ODOMETER`    | None    | A value to set the odometer. You can customize it using the `AXES` parameter to specify the desired axis and the `UNIT` parameter to set the measurement unit for the value.                                            |
| `AXES`            | "xyz"   | The axis to be used with `SET_MAINTENANCE` and `SET_ODOMETER`.  It can be 'x', 'y', 'z' or any combination of them.                                                                                                     |
| `UNIT`            | None    | The unit to be used with `SET_MAINTENANCE` and `SET_ODOMETER` or alone. It can be 'mm', 'm' or 'km'. `SET_MAINTENANCE` and `SET_ODOMETER` will use "km" as default.                                                     |
| `RELATIVE`        | False   | If set to `True`, the `SET_MAINTENANCE` and `SET_ODOMETER` values will be relative to the current odometer values.                                                                                                      |