import sys
import os
from threading import Thread

from fpme.hid_input import InputManager

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from fpme import train_control, tk_gui, switches, signal_gen


if __name__ == '__main__':
    control = train_control.TrainControl()
    groups = {
        'COM3': None,
        'COM6': None,
    }
    station_port = 'COM3'
    ports = [p for p in signal_gen.list_com_ports(include_bluetooth=False) if 'Prolific' in p[1]]
    for port, desc, _ in ports:
        control.add_rs232_generator(port, groups.get(port) if len(ports) > 1 else None)
    if not control.generator.get_open_ports():
        control.add_rs232_generator('debug1:on')
        # control.add_rs232_generator('debug2:off')
    control.set_lights_on(True)
    control.set_sound_on(True)
    control.power_on(None, 'launch')
    switch_manager = switches.SwitchManager()
    switch_controller = switches.StationSwitchesController(switch_manager, control.generator, station_port, max_train_count=4 if len(ports) > 1 else 10)
    inputs = InputManager(control)
    inputs.start_detection()
    PORT = 80
    # Thread(target=lambda: dash_app.Server(control).launch(port=PORT)).start()
    tk_gui.TKGUI(control, switch_controller, inputs, infos=[], fullscreen=False).launch()
