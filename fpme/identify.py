import platform
import sys
import time

from fpme import signal_gen, trains


if __name__ == '__main__':
    if len(sys.argv) <= 1:
        print("Please specify which train to identify, either IGBT or GTO", file=sys.stderr)
        exit()

    if platform.system() == 'Windows':
        port = 'COM5'
    else:
        port = '/dev/ttyUSB0'
    print(f"🛈 Preparing signal generator for port '{port}'")
    GENERATOR = signal_gen.ProcessSpawningGenerator(port)

    train = trains.get_by_name(sys.argv[1])
    print(f"Identifying {train}")
    GENERATOR.set(train.address, 0, False, {0: True, 2: True})
    for other_train in [t for t in trains.TRAINS if t != train]:
        GENERATOR.set(other_train.address, 0, False, {0: False, 2: False})
    GENERATOR.start()
    print(f"Sending signal. {train} lights switched on and sound enabled.")
    while True:
        time.sleep(.2)
        if GENERATOR.is_short_circuited:
            print("No power on tracks")
            time.sleep(15)
            GENERATOR.start()
