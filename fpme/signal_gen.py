import threading
import time
from multiprocessing import Value, Process, Queue

import serial


SERIAL_PORT = None  # 'COM1'


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

    def velocity_packet(self, address: int, speed: int, reverse: bool, func: bool):
        """
        Generate the bytes for RS-232 to send a Märklin-Motorola message to a locomotive.

        :param reverse: whether train is in reverse mode
        :param address: locomotive address between 1 and 80
        :param func: whether the locomotive's primary function is active
        :param speed: speed value: -14 to 14, 1 for direction change
        :return: package bytes for RS-232
        """
        assert 0 <= speed <= 14
        speed = speed + 1 if speed else 0
        packet = ALL_ADDRESSES[address] + (T[1] if func else T[0]) + self.velocity_bytes(speed, reverse)
        return bytes(packet)

    def velocity_bytes(self, speed: int, reverse: bool):
        raise NotImplementedError()

    def turn_packet(self, address: int, func: bool):
        raise NotImplementedError()


class Motorola1(MaerklinProtocol):

    def velocity_bytes(self, speed: int, reverse: bool):
        return T[speed & 1] + T[(speed >> 1) & 1] + T[(speed >> 2) & 1] + T[speed >> 3]

    def turn_packet(self, address: int, func: bool):
        """
        This packet indicates that a train should change direction.

        :param address: locomotive address
        :param func: whether the locomotive's primary function is active
        :return: package bytes for RS-232
        """
        packet = ALL_ADDRESSES[address] + (T[1] if func else T[0]) + self.velocity_bytes(1, False)
        return bytes(packet)


class Motorola2(MaerklinProtocol):

    def velocity_bytes(self, speed: int, reverse: bool):
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

    def turn_packet(self, address: int, func: bool):
        return None


class ProcessSpawningGenerator:

    def __init__(self):
        self._active = Value('b', False)
        self._short_circuited = Value('b', False)
        self._queue = Queue()
        self._process = Process(target=setup_generator, args=(self._queue, self._active, self._short_circuited))
        self._process.start()

    def set(self, address: int, speed: int, reverse: bool, func: bool, protocol: MaerklinProtocol = None):
        self._queue.put(('set', address, speed, reverse, func, protocol))

    def start(self):
        self._queue.put(('start',))

    def stop(self):
        self._active.value = False

    @property
    def is_sending(self):
        return bool(self._active.value) and not bool(self._short_circuited.value)


def setup_generator(queue: Queue, active: Value, short_circuited: Value):
    gen = SignalGenerator(active, short_circuited)
    while True:
        cmd = queue.get(block=True)
        getattr(gen, cmd[0])(*cmd[1:])


class SignalGenerator:

    def __init__(self, active: Value, short_circuited: Value):
        self.protocol = Motorola2()
        self._active = active
        self._data = {}  # address -> (speed, reverse, func)
        self._packets = {}
        self._turn_packets = {}
        self._turn_addresses = []
        self.immediate_repetitions = 2
        self._idle_packet = self.protocol.velocity_packet(80, 0, False, False)
        self._override_protocols = {}
        self._short_circuited = short_circuited
        self.stop_on_short_circuit = False
        self.on_short_circuit = None  # function without parameters
        if SERIAL_PORT is not None:
            ser = serial.Serial(port=SERIAL_PORT, baudrate=38400, parity=serial.PARITY_NONE,
                                stopbits=serial.STOPBITS_ONE, bytesize=serial.SIXBITS,
                                write_timeout=0,  # non-blocking write
                                rtscts=False,  # no flow control
                                dsrdtr=False,  # no flow control
                                )
            ser.is_open or ser.open()
            assert ser.is_open, f"Failed to open serial port {SERIAL_PORT}"
            ser.setRTS(False)
            ser.setDTR(True)
            self._ser = ser
        else:
            self._ser = None

    def set(self, address: int, speed: int, reverse: bool, func: bool, protocol: MaerklinProtocol = None):
        assert 0 < address < 80
        assert 0 <= speed <= 14
        if protocol is None and address in self._override_protocols:
            del self._override_protocols[address]
        elif protocol is not None:
            self._override_protocols[address] = protocol
        if address in self._data and self._data[address][1] != reverse:
            self._turn_addresses.append(address)
        self._data[address] = (speed, reverse, func)
        self._packets[address] = (protocol or self.protocol).velocity_packet(address, speed, reverse, func)
        self._turn_packets[address] = (protocol or self.protocol).turn_packet(address, func)

    def start(self):
        assert not self._active.value
        threading.Thread(target=self.run, name='RS_232_Signal_Generator').start()

    def run(self):
        assert not self._active.value
        self._active.value = True
        self._time_started_sending = time.perf_counter()
        while self._active.value:
            if self._ser is None:
                print(f"Here be signal: {self._packets}")
                time.sleep(0.5)
                continue
            self._short_circuited.value, newly_short_circuited = self._ser.getCTS(), self._ser.getCTS() and not self._short_circuited.value
            if self._short_circuited.value:
                newly_short_circuited and self.on_short_circuit()
                if self.stop_on_short_circuit:
                    return
                else:
                    time.sleep(0.1)
            else:  # Send data on serial port
                if not self._data:
                    self._send(self._idle_packet)
                for address, vel_packet in dict(self._packets).items():
                    if address in self._turn_addresses:
                        self._turn_addresses.remove(address)
                        if self._turn_packets[address] is not None:
                            for _rep in range(2):
                                self._send(self._turn_packets[address])
                    for _rep in range(self.immediate_repetitions):
                        self._send(vel_packet)
                    # time.sleep(6200e-6 - 1250e-6)

    def _send(self, packet):
        self._ser.write(packet)
        # time.sleep(len(packet) * 208e-6)
        # time.sleep(1250e-6)  # >= 3 t-bits (6 bytes) pause between signals
        t = time.perf_counter()
        while time.perf_counter() < t + 5.944e-3:
            pass  # manual sleep, time.sleep() is not precise enough
        # time.sleep(350e-6)  # >= 3 t-bits (6 bytes) pause between signals
        # Measured: 1.7 ms between equal packets in pair, 6 ms between different pairs


if __name__ == '__main__':
    gen = ProcessSpawningGenerator()
    print(f"Sending: {gen.is_sending}")
    gen.set(1, 0, False, False)
    gen.start()
    print(f"Sending: {gen.is_sending}")
    time.sleep(1)
    print(f"Sending: {gen.is_sending}")
    gen.set(1, 14, True, False)
    time.sleep(4)
    gen.stop()
    time.sleep(2)
    gen.start()
