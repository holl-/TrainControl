import sys
import os
from threading import Thread

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from fpme import train_control, train_def, tk_gui, dash_app, switches, signal_gen


if __name__ == '__main__':
    control = train_control.TrainControl()
    switches = switches.SwitchManager()
    for port, desc, _ in signal_gen.list_com_ports(include_bluetooth=False):
        if 'Prolific' in desc:
            control.add_rs232_generator(port)
    if not control.generator.get_open_ports():
        control.add_rs232_generator('debug1:on')
        control.add_rs232_generator('debug2:off')
    # control.add_rs232_generator('debug1', [train for train in train_def.TRAINS if train != train_def.ICE])
    # control.add_rs232_generator('debug2', [train_def.ICE])
    control.power_on(None)
    PORT = 80
    Thread(target=lambda: dash_app.Server(control).launch(port=PORT)).start()
    tk_gui.TKGUI(control, switches, infos=[f"http://{dash_app.LOCAL_IP}{'' if PORT == 80 else f':{PORT}'}/"], fullscreen=False).launch()

