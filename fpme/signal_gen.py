import os
import threading
import time
from dataclasses import dataclass
from multiprocessing import Value, Process, Queue, Manager
from ctypes import c_char_p
from typing import List, Dict, Tuple, Callable

import serial
from serial import SerialException
import serial.tools.list_ports


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
        speed = speed or 0
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


MM1 = Motorola1()
MM2 = Motorola2()


@dataclass
class GeneratorState:
    serial_port: str
    addresses: Tuple[int]
    active: Value
    short_circuited: Value
    error_message: Value
    last_stopped: float = None  # mutable


def list_com_ports(include_bluetooth=False):
    ports = serial.tools.list_ports.comports()
    for port, desc, hwid in sorted(ports):
        is_bluetooth = 'bluetooth' in desc.lower() or '00001101-0000-1000-8000-00805F9B34FB' in hwid.upper()
        if not is_bluetooth or include_bluetooth:
            yield port, desc, hwid


class SubprocessGenerator:

    def __init__(self, max_generators=1):
        self.max_generators = max_generators
        self._subprocess_run = Queue()
        self._process = None
        self._manager = None
        self._generator_states: Dict[str, GeneratorState] = {}  # serial port -> state
        self._address_states: Dict[int, tuple] = {}  # address -> state
        self._manager = Manager()
        self._all_active = [Value('b', False) for _ in range(max_generators)]
        self._all_short_circuited = [Value('b', False) for _ in range(max_generators)]
        self._all_error = [self._manager.Value(c_char_p, "") for _ in range(max_generators)]

    def setup(self):
        def async_setup():
            with self._manager:
                self._process = Process(target=subprocess_main, args=(self._subprocess_run, self._all_active, self._all_short_circuited, self._all_error))
                self._process.start()
                self._process.join()
                print("Child process terminated.")
        threading.Thread(target=async_setup).start()

    def open_port(self, serial_port: str, addresses: Tuple[int] = None):
        assert serial_port is not None, f"use the prefix 'debug' for fake ports instead of {serial_port}"
        i = len(self._generator_states)
        state = GeneratorState(serial_port, addresses, active=self._all_active[i], short_circuited=self._all_short_circuited[i], error_message=self._all_error[i])
        self._generator_states[serial_port] = state
        self._subprocess_run.put(('open_port', serial_port, addresses))

    def get_open_ports(self) -> Tuple[str]:
        return tuple(self._generator_states.keys())

    def set(self, address: int, speed: int or None, reverse: bool, functions: Dict[int, bool], protocol: RS232Protocol = None):
        if address in self._address_states and self._address_states[address] == (speed, reverse, functions, protocol):
            return  # already set
        assert isinstance(address, int)
        assert isinstance(speed, int) or speed is None
        assert isinstance(reverse, bool)
        assert isinstance(functions, dict), "functions must be a Dict[int, bool]"
        assert all(isinstance(f, int) for f in functions.keys()), "functions must be a Dict[int, bool]"
        assert all(isinstance(v, bool) for v in functions.values()), "functions must be a Dict[int, bool]"
        self._address_states[address] = (speed, reverse, functions, protocol)
        self._subprocess_run.put(('set', address, speed, reverse, functions, protocol))

    def start(self, serial_port: str):
        self._subprocess_run.put(('start', serial_port))

    def stop(self, serial_port: str):
        state = self._generator_states[serial_port]
        state.active.value = False
        state._last_stopped = time.perf_counter()

    def is_sending_on(self, serial_port: str):
        state = self._generator_states[serial_port]
        return bool(state.active.value) and not bool(state.short_circuited.value)

    def terminate(self):
        self._subprocess_run.put(('terminate',))
        time.sleep(.1)
        self._process.terminate()
        # self._process_manager.close()

    def is_short_circuited(self, serial_port: str):
        state = self._generator_states[serial_port]
        return bool(state.short_circuited.value)

    def get_error(self, serial_port: str) -> str:
        """Empty string means no error"""
        state = self._generator_states[serial_port]
        return state.error_message.value

    def time_since_last_stopped(self, serial_port: str):
        state = self._generator_states[serial_port]
        if state.last_stopped is None:
            return float('-inf')
        else:
            return time.perf_counter() - state.last_stopped

    def is_in_reverse(self, address: int):
        return self._address_states[address][1]


# ------------------ Executed in subprocess from here on --------------------

def subprocess_main(queue: Queue, active, short_circuited, error):
    main = SignalGenProcessInterface(active, short_circuited, error)
    while True:
        cmd = queue.get(block=True)
        print(f"Subprocess received: {cmd}")
        getattr(main, cmd[0])(*cmd[1:])


class SignalGenProcessInterface:

    def __init__(self, all_active, all_short_circuited, all_error):
        self.all_active = list(all_active)
        self.all_short_circuited = list(all_short_circuited)
        self.all_error = list(all_error)
        self.generators: Dict[str, SignalGenerator] = {}
        self.addresses: Dict[str, Tuple[int]] = {}
        self.state: Dict[int, tuple] = {}
        self.scheduler = ThreadScheduler()

    def open_port(self, serial_port: str, addresses):
        assert serial_port not in self.generators
        gen = SignalGenerator(serial_port, self.scheduler, self.all_active.pop(0), self.all_short_circuited.pop(0), self.all_error.pop(0))
        for address, (speed, reverse, functions, protocol) in self.state.items():
            if addresses is None or address in addresses:
                gen.set(address, speed, reverse, functions, protocol)
        self.generators[serial_port] = gen
        self.addresses[serial_port] = addresses

    def set(self, address: int, speed: int or None, reverse: bool, functions: Dict[int, bool], protocol: RS232Protocol = None):
        self.state[address] = (speed, reverse, functions, protocol)
        for serial_port, generator in self.generators.items():
            addresses = self.addresses[serial_port]
            if addresses is None or address in addresses:
                generator.set(address, speed, reverse, functions, protocol)

    def start(self, serial_port: str):
        self.generators[serial_port].start()

    def terminate(self):
        os._exit(0)


class ThreadScheduler:
    """Sleep with sub-millisecond precision"""

    def __init__(self):
        self.scheduler_event = threading.Event()
        self.events = {}
        self.event_queue = []
        def work_loop():
            while True:
                if not self.event_queue:
                    time.sleep(0)
                    continue
                event, at_time = self.event_queue.pop(0)
                while time.perf_counter() < at_time:
                    pass
                event.set()
                self.scheduler_event.wait()
                self.scheduler_event.clear()
        threading.Thread(target=work_loop, name='RS_232_Signal_Generator_Worker').start()

    def start_thread(self, target: Callable, name: str):
        def thread_fun():
            target()
            self.scheduler_event.set()
        threading.Thread(target=thread_fun, name=name).start()

    def sleep(self, source, for_time: float):
        """Blocks until task is done"""
        now = time.perf_counter()
        if source in self.events:
            event = self.events[source]
        else:
            event = threading.Event()
            self.events[source] = event
        self.event_queue.append((event, now + for_time))
        self.scheduler_event.set()
        event.wait()
        event.clear()


class SignalGenerator:

    def __init__(self, serial_port: str, scheduler: ThreadScheduler, active: Value, short_circuited: Value, error_message: Value):
        self.serial_port = serial_port
        self.protocol = Motorola2()
        self.scheduler = scheduler
        self._active = active
        self._data = {}  # address -> (speed, reverse, func)
        self._packets = {}
        self._priority_packets = []
        self._idle_packet = self.protocol.status_packets(80, 0, False, {0: False})[0]
        self._override_protocols = {}
        self._short_circuited = short_circuited
        self._error_message = error_message
        self.stop_on_short_circuit = True
        self.on_short_circuit = lambda: print("Short circuit detected")  # function without parameters
        self._time_started_sending = None  # wait a bit before detecting short circuits
        self._ser = None
        self._time_created = time.perf_counter()
        if not serial_port.startswith('debug'):
            try:
                print(f"Opening serial port {serial_port}...")
                # ser = serial.Serial(port=serial_port, baudrate=9600)
                # ser.close()  # AKYGA adapter does not like being opened twice with the same config
                ser = serial.Serial(port=serial_port, baudrate=38400, parity=serial.PARITY_NONE,
                                    stopbits=serial.STOPBITS_ONE, bytesize=serial.SIXBITS,
                                    write_timeout=None,  # non-blocking write
                                    rtscts=False,  # no flow control
                                    dsrdtr=False,  # no flow control
                                    )
                # ser = serial.Serial(port=serial_port, baudrate=38400, parity=serial.PARITY_NONE,
                #                     stopbits=serial.STOPBITS_ONE, bytesize=serial.SIXBITS,
                #                     write_timeout=None,  # non-blocking write
                #                     rtscts=False,  # no flow control
                #                     dsrdtr=False,  # no flow control
                #                     )
                print(f"{serial_port} opened successfully")
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
        self._data[address] = (speed, reverse, functions)
        # --- create signal packets ---
        packets = self._packets[address] = (protocol or self.protocol).status_packets(address, speed, reverse, functions)
        if address in self._data and self._data[address][1] != reverse:
            turn_packet = (protocol or self.protocol).turn_packet(address, functions)
            if turn_packet:
                self._priority_packets.append(turn_packet)
        self._priority_packets.extend(packets)

    def start(self):
        if self._active.value:
            return  # already running
        # assert not self._active.value  # ToDo this breaks the app sometimes
        self.scheduler.start_thread(target=self.run, name='RS_232_Signal_Generator')

    def run(self):
        assert not self._active.value
        self._active.value = True
        self._time_started_sending = time.perf_counter()
        while self._active.value:
            if self._ser is not None:
                short_circuited = time.perf_counter() > self._time_started_sending + 0.1 and self._ser.getCTS()  # 0.1 seconds to test for short circuits
            else:
                time.sleep(1)
                short_circuited = False
                print(f"Here be signal: {self._packets}")
            self._short_circuited.value, newly_short_circuited = short_circuited, short_circuited and not self._short_circuited.value
            if self._short_circuited.value:
                if newly_short_circuited and self.on_short_circuit is not None:
                    self.on_short_circuit()
                if self.stop_on_short_circuit:
                    self._active.value = False
                    return
            # --- Send data on serial port ---
            if not self._data:
                self._send(self._idle_packet)
            for address, status_packets in dict(self._packets).items():
                for packet in status_packets:
                    self._send(packet)  # Sends each packet twice, else trains will ignore it
                    # print(' '.join('{:02x}'.format(x) for x in packet))

    def _send(self, packet):
        while self._priority_packets:
            packet = self._priority_packets.pop(0)
            for i in range(2):
                self._ser is not None and self._ser.write(packet)
                self.scheduler.sleep(self, 5.944e-3)
        for i in range(2):
            self._ser is not None and self._ser.write(packet)
            self.scheduler.sleep(self, 5.944e-3)  # custom sleep, time.sleep() is not precise enough
            # Measured: 1.7 ms between equal packets in pair, 6 ms between different pairs


if __name__ == '__main__':
    gen = SubprocessGenerator()
    gen.setup()
    gen.open_port('COM8')
    gen.start('COM8')
    # S-Bahn: 0=Licht außen, 1=Licht innen, 2=Motor 3=Horn, 4=Sofort auf Geschwindigkeit
    # E-Lok (BW): 0=Licht, 1=- 2=Nebelscheinwerfer, 3: Fahrtlicht hinten, 4: Sofort auf Geschwindigkeit

    gen.set(24, 0, True, {0: False})
    while True:
        print(gen.is_short_circuited('COM8'), gen.is_sending_on('COM8'))
        time.sleep(.1)

    # for i in range(10):
    #     for f in [0, 1, 2, 3, 4]:
    #         gen.set(1, 5, False, {i: i == f for i in range(5)})
    #         print(f"Function {f}")
    #         time.sleep(10)
    # time.sleep(10)
    # gen.set(1, 0, True, {})

    # gen.set(24, 7, False, False, protocol=Motorola1())  # E-Lok (DB)
