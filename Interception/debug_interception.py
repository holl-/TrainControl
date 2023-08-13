import time

import interception

kdevice = interception.listen_to_keyboard()
mdevice = interception.listen_to_mouse()

interception.inputs.keyboard = kdevice
interception.inputs.mouse = mdevice

with interception.inputs.capture_keyboard():
    time.sleep(10)