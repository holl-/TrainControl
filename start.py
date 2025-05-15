import sys
import os

from fpme.hid_input import InputManager
from fpme.relay8 import RelayManager, Relay8
from fpme.terminus import Terminus

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from fpme import train_control, tk_gui, signal_gen


if __name__ == '__main__':
    control = train_control.TrainControl()
    ports = [p for p in signal_gen.list_com_ports(include_bluetooth=False) if 'Prolific' in p[1]]
    for port, desc, _ in ports:
        control.add_rs232_generator(port)
    if not control.generator.get_open_ports():
        control.add_rs232_generator('debug1:on')
        # control.add_rs232_generator('debug2:off')
    control.set_lights_on(True)
    control.set_sound_on(False)
    control.power_on(None, 'launch')
    inputs = InputManager(control)
    inputs.start_detection()
    relay = RelayManager()
    # Thread(target=lambda: dash_app.Server(control).launch(port=PORT)).start()
    gui = tk_gui.TKGUI(control, relay, inputs, infos=[], fullscreen=False)

    def setup_terminal(relay: Relay8):
        print("Relay detected. Setting up terminus.")
        terminus = Terminus(relay, control, ports[0][0])
        gui.set_terminus(terminus)
        inputs.set_terminus(terminus)
    relay.on_connected(setup_terminal)

    gui.launch()
