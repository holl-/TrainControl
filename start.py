import sys
import os
from threading import Thread

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from fpme import train_control, train_def, tk_gui, dash_app


if __name__ == '__main__':
    control = train_control.TrainControl()
    control.add_rs232_generator('debug1')
    control.add_rs232_generator('debug2', [train_def.ICE])
    control.power_on(train_def.ICE)
    Thread(target=lambda: dash_app.Server(control).launch(port=80)).start()
    tk_gui.TKGUI(control).launch()

