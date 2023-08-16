import sys
import os
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from fpme import tk_gui, train_control, train_def

if __name__ == '__main__':
    # dash_app.start(port=80, serial_port='COM5')



    control = train_control.TrainControl()
    control.add_rs232_generator(None)
    control.power_on(train_def.ICE)
    print("Power on")
