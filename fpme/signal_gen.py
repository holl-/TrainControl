import threading
import time
from multiprocessing import Value, Process, Queue, Manager
from ctypes import c_char_p
from typing import List, Dict

import serial
from serial import SerialException


T = TERNARY_BITS = [(63, 63), (0, 0), (0, 63)]  # 416 ms per bit
# 1 trit = 2 bits
# Every bit starts with a rising flank, 1 stays up, 0 goes down


def _all_addresses():
    result = []
    for bit1 in TERNARY_BITS:
        for bit2 in TERNARY_BITS:
            for bit3 in TERNARY_BITS:
                for bit4 in TERNARY_BITS:
                    result.append(bit4 + bit3 + bit2 + bit1)
    return tuple(result)


ALL_ADDRESSES = _all_addresses()


class RS232Protocol:

    def status_packets(self, address: int, speed: int or None, reverse: bool, functions: Dict[int, bool]) -> List[bytes]:
        raise NotImplementedError

    def turn_packet(self, address: int, functions: Dict[int, bool]) -> bytes or None:
        raise NotImplementedError


class Motorola1(RS232Protocol):

    def status_packets(self, address: int, speed: int or None, reverse: bool, functions: Dict[int, bool]) -> List[bytes]:
        """
        MM1 only sends a velocity packet consisting of

        * Address (4 trits)
        * Function 0 (1 trit)
        * Speed between 0 and 14, (4 trits)
        """
        assert speed is None or 0 <= speed <= 14
        f0 = functions.get(0, True)
        speed = speed + 1 if speed else speed  # keep 0 and None
        velocity_trits = T[speed & 1] + T[(speed >> 1) & 1] + T[(speed >> 2) & 1] + T[speed >> 3]
        packet = ALL_ADDRESSES[address] + (T[1] if f0 else T[0]) + velocity_trits
        return [bytes(packet)]

    def turn_packet(self, address: int, functions: Dict[int, bool]) -> bytes:
        """
        This packet indicates that a train should change direction.

        :return: package bytes for RS-232
        """
        f0 = functions.get(0, True)
        packet = ALL_ADDRESSES[address] + (T[1] if f0 else T[0]) + T[1] + T[0] + T[0] + T[0]
        return bytes(packet)


class Motorola2(RS232Protocol):

    def status_packets(self, address: int, speed: int or None, reverse: bool, functions: Dict[int, bool]) -> List[bytes]:
        assert speed is None or 0 <= speed <= 14
        f0 = functions.get(0, True)
        speed = speed + 1 if speed else speed  # keep 0 and None
        velocity_packet = ALL_ADDRESSES[address] + (T[1] if f0 else T[0]) + self.velocity_bytes(speed, reverse)
        packets = [velocity_packet]
        for function, status in functions.items():
            if function > 0:
                function_packet = ALL_ADDRESSES[address] + (T[1] if f0 else T[0]) + self.function_bytes(speed, function, status)
                packets.append(function_packet)
        return [bytes(p) for p in packets]

    def velocity_bytes(self, speed: int, reverse: bool):
        if speed is None:
            bits = 1, 1, 0, 0, 0, 0, 0, 0
            return tuple(0 if b else 63 for b in bits)
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

    def function_bytes(self, speed: int, function: int, status: bool):
        if function == 1:
            if speed == 3 and not status:
                b2, b4, b6, b8 = 1, 0, 1, 0
            elif speed == 11 and status:
                b2, b4, b6, b8 = 0, 1, 0, 1
            else:
                b2, b4, b6, b8 = 1, 1, 0, status
        elif function == 2:
            if speed == 4 and not status:
                b2, b4, b6, b8 = 1, 0, 1, 0
            elif speed == 12 and status:
                b2, b4, b6, b8 = 0, 1, 0, 1
            else:
                b2, b4, b6, b8 = 0, 0, 1, status
        elif function == 3:
            if speed == 6 and not status:
                b2, b4, b6, b8 = 1, 0, 1, 0
            elif speed == 14 and status:
                b2, b4, b6, b8 = 0, 1, 0, 1
            else:
                b2, b4, b6, b8 = 0, 1, 1, status
        elif function == 4:
            if speed == 7 and not status:
                b2, b4, b6, b8 = 1, 0, 1, 0
            elif speed == 15 and status:
                b2, b4, b6, b8 = 0, 1, 0, 1
            else:
                b2, b4, b6, b8 = 1, 1, 1, status
        else:
            raise ValueError(function)
        bits = [speed & 1, b2, (speed >> 1) & 1, b4, (speed >> 2) & 1, b6, speed >> 3, b8]
        return tuple(0 if b else 63 for b in bits)

    def turn_packet(self, address: int, functions: Dict[int, bool]) -> None:
        return None


class ProcessSpawningGenerator:

    def __init__(self, serial_port: str):
        manager = Manager()
        self._active = Value('b', False)
        self._short_circuited = Value('b', False)
        self._error_message = manager.Value(c_char_p, "")
        self._queue = Queue()
        self._process = Process(target=setup_generator, args=(serial_port, self._queue, self._active, self._short_circuited, self._error_message))
        self._process.start()

    def set(self, address: int, speed: int or None, reverse: bool, functions: Dict[int, bool], protocol: RS232Protocol = None):
        assert isinstance(address, int)
        assert isinstance(speed, int) or speed is None
        assert isinstance(reverse, bool)
        assert isinstance(functions, dict), "functions must be a Dict[int, bool]"
        assert all(isinstance(f, int) for f in functions.keys()), "functions must be a Dict[int, bool]"
        assert all(isinstance(v, bool) for v in functions.values()), "functions must be a Dict[int, bool]"
        self._queue.put(('set', address, speed, reverse, functions, protocol))

    def start(self):
        self._queue.put(('start',))

    def stop(self):
        self._active.value = False

    @property
    def is_sending(self):
        return bool(self._active.value) and not bool(self._short_circuited.value)

    def terminate(self):
        self._process.terminate()

    @property
    def is_short_circuited(self):
        return bool(self._short_circuited.value)

    @property
    def error_message(self):
        return self._error_message.value

    @property
    def has_error(self):
        return bool(self._error_message.value)


def setup_generator(serial_port: str, queue: Queue, active: Value, short_circuited: Value, error_message: Value):
    gen = SignalGenerator(serial_port, active, short_circuited, error_message)
    while True:
        cmd = queue.get(block=True)
        getattr(gen, cmd[0])(*cmd[1:])


class SignalGenerator:

    def __init__(self, serial_port: str, active: Value, short_circuited: Value, error_message: Value):
        self.protocol = Motorola2()
        self._active = active
        self._data = {}  # address -> (speed, reverse, func)
        self._packets = {}
        self._turn_packets = {}
        self._turn_addresses = []
        self._idle_packet = self.protocol.status_packets(80, 0, False, {0: False})[0]
        self._override_protocols = {}
        self._short_circuited = short_circuited
        self._error_message = error_message
        self.stop_on_short_circuit = True
        self.on_short_circuit = lambda: print("Short circuit detected")  # function without parameters
        self._time_started_sending = None  # wait a bit before detecting short circuits
        self._ser = None
        if serial_port:
            try:
                ser = serial.Serial(port=serial_port, baudrate=38400, parity=serial.PARITY_NONE,
                                    stopbits=serial.STOPBITS_ONE, bytesize=serial.SIXBITS,
                                    write_timeout=None,  # non-blocking write
                                    rtscts=False,  # no flow control
                                    dsrdtr=False,  # no flow control
                                    )
                self._ser = ser
            except SerialException as exc:
                print(exc)
                self._error_message.value = str(exc)
                return
            try:
                ser.is_open or ser.open()
                assert ser.is_open, f"Failed to open serial port {serial_port}"
                ser.setRTS(False)
                ser.setDTR(True)
            except SerialException as exc:
                print(exc)
                self._error_message.value = str(exc)

    def set(self, address: int, speed: int or None, reverse: bool, functions: Dict[int, bool], protocol: RS232Protocol = None):
        assert 0 < address < 80
        assert speed is None or 0 <= speed <= 14
        if protocol is None and address in self._override_protocols:
            del self._override_protocols[address]
        elif protocol is not None:
            self._override_protocols[address] = protocol
        if address in self._data and self._data[address][1] != reverse:
            self._turn_addresses.append(address)
        self._data[address] = (speed, reverse, functions)
        self._packets[address] = (protocol or self.protocol).status_packets(address, speed, reverse, functions)
        self._turn_packets[address] = (protocol or self.protocol).turn_packet(address, functions)

    def start(self):
        # assert not self._active.value  # ToDo this breaks the app sometimes
        threading.Thread(target=self.run, name='RS_232_Signal_Generator').start()

    def run(self):
        assert not self._active.value
        self._active.value = True
        self._time_started_sending = time.perf_counter()
        while self._active.value:
            if self._ser is None:
                # print(f"Here be signal: {self._packets}")
                time.sleep(0.5)
                continue
            short_circuited = time.perf_counter() > self._time_started_sending + 0.1 and self._ser.getCTS()  # 0.1 seconds to test for short circuits
            self._short_circuited.value, newly_short_circuited = short_circuited, short_circuited and not self._short_circuited.value
            if self._short_circuited.value:
                if newly_short_circuited and self.on_short_circuit is not None:
                    self.on_short_circuit()
                if self.stop_on_short_circuit:
                    self._active.value = False
                    return
            # Send data on serial port
            if not self._data:
                self._send(self._idle_packet)
            for address, status_packets in dict(self._packets).items():
                if address in self._turn_addresses:
                    self._turn_addresses.remove(address)
                    if self._turn_packets[address] is not None:
                        for _rep in range(2):
                            self._send(self._turn_packets[address])
                for packet in status_packets:
                    # print(' '.join('{:02x}'.format(x) for x in packet))
                    for _rep in range(2):  # Send each packet twice, else trains will ignore it
                        self._send(packet)

    def _send(self, packet):
        self._ser.write(packet)
        t = time.perf_counter()
        while time.perf_counter() < t + 5.944e-3:
            pass  # manual sleep, time.sleep() is not precise enough
        # Measured: 1.7 ms between equal packets in pair, 6 ms between different pairs


if __name__ == '__main__':
    gen = ProcessSpawningGenerator('COM5')
    gen.start()
    # S-Bahn: 0=Licht außen, 1=Licht innen, 2=Motor 3=Horn, 4=Sofort auf Geschwindigkeit
    # E-Lok (BW): 0=Licht, 1=- 2=Nebelscheinwerfer, 3: Fahrtlicht hinten, 4: Sofort auf Geschwindigkeit

    gen.set(1, 0, False, {4: True})
    time.sleep(1)
    gen.set(1, 11, False, {4: True})
    time.sleep(3)
    gen.set(1, 0, False, {4: True})
    # for i in range(10):
    #     for f in [0, 1, 2, 3, 4]:
    #         gen.set(1, 5, False, {i: i == f for i in range(5)})
    #         print(f"Function {f}")
    #         time.sleep(10)
    # time.sleep(10)
    # gen.set(1, 0, True, {})

    # gen.set(24, 7, False, False, protocol=Motorola1())  # E-Lok (DB)
