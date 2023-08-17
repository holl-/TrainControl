import sys
import os
import time

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from fpme import train_control, train_def, tk_gui

if __name__ == '__main__':
    # dash_app.start(port=80, serial_port='COM5')



    control = train_control.TrainControl()
    control.add_rs232_generator(None)
    control.power_on(train_def.ICE)

    tk_gui.TKGUI(control).launch()

    time.sleep(30)
    control.terminate()
