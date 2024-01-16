import requests

_MOONRAKER_ADDRESS = "127.0.0.1:7125"

base_url = f"http://{_MOONRAKER_ADDRESS}/server/database/item?namespace=motion_minder"
for axis in ["x", "y", "z"]:
    for key in ["next_maintenance", "odometer_on_reset", "odometer"]:
        r = requests.delete(f"{base_url}&key={key}_{axis}", timeout=1)
