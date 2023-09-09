import sys
import os
from threading import Thread

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from fpme import train_control, train_def, tk_gui, dash_app, switches


if __name__ == '__main__':
    control = train_control.TrainControl()
    switches = switches.SwitchManager()
    control.add_rs232_generator('COM4')
    # control.add_rs232_generator('debug1', [train for train in train_def.TRAINS if train != train_def.ICE])
    # control.add_rs232_generator('debug2', [train_def.ICE])
    control.power_on(None)
    PORT = 80
    Thread(target=lambda: dash_app.Server(control).launch(port=PORT)).start()
    tk_gui.TKGUI(control, switches, infos=[f"http://{dash_app.LOCAL_IP}{'' if PORT == 80 else f':{PORT}'}/"], fullscreen=False).launch()

