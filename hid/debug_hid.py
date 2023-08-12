import os
os.chdir("C:\\Users\\phili\\PycharmProjects\\TrainControl\\hid\\hidapi-win\\x64")

import hid

for dev_info in hid.enumerate():
    vid = dev_info['vendor_id']
    pid = dev_info['product_id']
    device = hid.Device(vid, pid)
    print(device.product, device.manufacturer, vid, pid)
    try:
        device.read(1, timeout=100)
        print(" +")
    except hid.HIDException as exc:
        print("-", exc)


# # Wireless Mouse
# vid = 12625
# pid = 12320
# device = hid.Device(vid, pid)
# device.read()
#
# while True:
#     data = device.read(64)
#     print(data)
