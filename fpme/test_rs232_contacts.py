import time

import serial

ser = serial.Serial(port='COM5', baudrate=38400, parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE, bytesize=serial.SIXBITS,
                    write_timeout=None,  # non-blocking write
                    rtscts=False,  # no flow control
                    dsrdtr=False,  # no flow control
                    )
ser.setDTR(True)
ser.setRTS(False)
while True:
    print(f"RI 1 {ser.getRI()}, DSR 2: {ser.getDSR()}, CD 3: {ser.getCD()}, Gleisstrom: {ser.getCTS()}")
    time.sleep(.2)

