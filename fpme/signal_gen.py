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
                    result.append(bit4 + bit3 + bit2 + bit1)
    return tuple(result)


ALL_ADDRESSES = _all_addresses()


class MaerklinProtocol:

    def packet(self, address: int, speed: int, reverse: bool, func: bool):
        """
        Generate the bytes for RS-232 to send a Märklin-Motorola message to a locomotive.

        :param reverse: whether train is in reverse mode
        :param address: locomotove address between 1 and 80
        :param func: whether function is active
        :param speed: speed value: -14 to 14, 1 for direction change
        :return: package bytes
        """
        packet = ALL_ADDRESSES[address] + (T[1] if func else T[0]) + self.velocity_bytes(speed, reverse)
        # print(packet)
        return bytes(packet)

    def velocity_bytes(self, speed: int, reverse: bool):
        raise NotImplementedError()


class Motorola1(MaerklinProtocol):

    def velocity_bytes(self, speed: int, reverse: bool):
        assert 0 <= speed <= 14
        speed = speed + 1 if speed else 0
        return T[speed & 1] + T[(speed >> 1) & 1] + T[(speed >> 2) & 1] + T[speed >> 3]


class Motorola2(MaerklinProtocol):

    def velocity_bytes(self, speed: int, reverse: bool):
        assert 0 <= speed <= 14
        if speed >= 7 and reverse:
            b2, b4, b6, b8 = [1, 0, 1, 0]
        elif speed <= 6 and reverse:
            b2, b4, b6, b8 = [1, 0, 1, 1]
        elif speed <= 6 and not reverse:
            b2, b4, b6, b8 = [0, 1, 0, 1]
        elif speed >= 7 and not reverse:
            b2, b4, b6, b8 = [0, 1, 0, 0]
        else:
            raise ValueError()
        bits = [speed & 1, b2, (speed >> 1) & 1, b4, (speed >> 2) & 1, b6, speed >> 3, b8]
        return tuple(0 if b else 63 for b in bits)


class SignalGenerator:

    def __init__(self, serial_port: str, protocol: MaerklinProtocol):
        ser = serial.Serial(
            port=serial_port,
            baudrate=38400,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.SIXBITS,
            # write_timeout=0,  # non-blocking write
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
        # TODO send reverse signal if speed reverses (E-Lok DB does not change direction)

    def run(self):
        assert not self._active
        self._active = True
        while self._active:
            if not self.data:
                pass  # TODO idle signal
            for address, (speed, func) in dict(self.data).items():
                for _rep in range(self.immediate_repetitions):
                    packet = self.protocol.packet(address, abs(speed), speed < 0, func)  # TODO emergency break through speed reversal?
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
    gen.set(48, 0, False)
    gen.run()
