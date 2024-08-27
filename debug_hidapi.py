"""
Requires VR-Park controllers to be in mode C.
"""
import hid  # pip install hidapi

# List all connected devices
for device_info in hid.enumerate():
    if device_info['vendor_id'] == 1452: # , PID: 556
        print(device_info)
        device = hid.device()
        device.open(device_info['vendor_id'], device_info['product_id'])

        # Read input reports
        while True:
            report = device.read(64)  # Adjust the size if necessary
            if report:
                print(f"Received report: {report}")

        device.close()




