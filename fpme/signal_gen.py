import threading
import time
import serial


TERNARY_BITS = [(63, 63), (0, 0), (0, 63)]  # 416 ms per bit
T = TERNARY_BITS


def _all_addresses():
    result = []
    for bit1 in TERNARY_BITS:
        for bit2 in TERNARY_BITS:
            for bit3 in TERNARY_BITS:
                for bit4 in TERNARY_BITS:
                    result.append(bit1 + bit2 + bit3 + bit4)
    return tuple(result)


ALL_ADDRESSES = _all_addresses()


class MaerklinProtocol:

    def packet(self, address: int, speed: int, func: bool):
        """
        Generate the bytes for RS-232 to send a Märklin-Motorola message to a locomotive.

        :param address: locomotove address between 1 and 80
        :param func: whether function is active
        :param speed: speed value: -14 to 14, 1 for direction change
        :return: package bytes
        """
        packet = ALL_ADDRESSES[address] + (T[1] if func else T[0]) + self.velocity_bytes(speed)
        return bytes(packet)

    def velocity_bytes(self, speed):
        raise NotImplementedError()


class Motorola1(MaerklinProtocol):

    def velocity_bytes(self, speed):
        return T[speed & 1] + T[(speed >> 1) & 1] + T[(speed >> 2) & 1] + T[speed >> 3]


class Motorola2(MaerklinProtocol):

    ALL_SPEEDS = [
        # -14, ... 14
    ]

    def velocity_bytes(self, speed):
        return self.ALL_SPEEDS[speed]  # TODO


class SignalGenerator:

    def __init__(self, serial_port: str, protocol: MaerklinProtocol):
        ser = serial.Serial(
            port=serial_port,
            baudrate=38400,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.SIXBITS,
            write_timeout=0,  # non-blocking write
        )
        ser.is_open or ser.open()
        assert ser.is_open
        self._ser = ser
        self.protocol = protocol
        self._active = False
        self.data = {}  # address -> (speed, func)
        self.immediate_repetitions = 2

    def set(self, address, speed, func):
        self.data[address] = (speed, func)

    def run(self):
        assert not self._active
        self._active = True
        while self._active:
            if not self.data:
                pass  # TODO idle signal
            for address, (speed, func) in self.data.items():
                for _rep in range(self.immediate_repetitions):
                    packet = self.protocol.packet(address, speed, func)
                    self._ser.write(packet)
                    time.sleep(len(packet) * 208e-6)
                    time.sleep(1250e-6)  # >= 3 t-bits (6 bytes) pause between signals

    def start(self):
        assert not self._active
        threading.Thread(target=self.run, name='RS_232_Signal_Generator').start()

    def stop(self):
        self._active = False


if __name__ == '__main__':
    gen = SignalGenerator('COM1', Motorola1())
    gen.set(78, 6, True)
    gen.run()
