"""
General-purpose (configurable) I/O pin on the Wiport.
Pins can control devices such as relays, servers, lights, monitor switches, sensors, and even processes such as data transfer.

Can be controlled via TCP or UDP.
"""
import socket
import threading


GET_FUNCTIONS = b'\x10'  # functions can only be set via 77FE

GET_DIRECTIONS = b'\x11'  # input (0) / output (1)
SET_DIRECTIONS = b'\x19'

GET_ACTIVE_LEVELS = b'\x12'  # active high (0) / active low (1)
SET_ACTIVE_LEVELS = b'\x16'

GET_CURRENT_STATES = b'\x13'  # active (1) / inactive (0)
SET_CURRENT_STATES = b'\x18'


def encode_parameter(bits: tuple or list):
    """ Convert 32 bools to 4 bytes """
    as_int = int(''.join(['1' if i else '0' for i in bits]), 2)
    return as_int.to_bytes(4, byteorder='big')


def decode_parameter(data: bytes):
    """ Convert 4 bytes to 32 boolean values """
    as_int = int.from_bytes(data, byteorder='big')
    binary = f"{as_int:032b}"
    return [b == '1' for b in binary]


NO_PARAMETER = bytes([0, 0, 0, 0])


# _ = encode_parameter([False] * 31 + [True])
# print(_)
# print(decode_parameter(_))


class WiPort:

    def __init__(self, ip_address, port=b'\x77f0'):
        self.ip_address = ip_address
        self.port = port
        self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP
        self._io_lock = threading.Lock()
        self._response_pending = False

    def _send_command_blocking(self, command_type, parameter1: bytes, parameter2: bytes):
        """
        Wiport sends response after every command.
        Wait for response before sending another command.

        Args:
            command_type: byte
            parameter1: 4 bytes
            parameter2: 4 bytes
        """
        with self._io_lock:
            self._response_pending = True
            self._udp.sendto(command_type + parameter1 + parameter2, (self.ip_address, self.port))  # 9 bytes
            response, addr = self._udp.recvfrom(5)
            assert response[0] == command_type
            self._response_pending = False
            return decode_parameter(response[1:])

    def get_functions(self):
        return self._send_command_blocking(GET_FUNCTIONS, NO_PARAMETER, NO_PARAMETER)

    def get_directions(self):
        return self._send_command_blocking(GET_DIRECTIONS, NO_PARAMETER, NO_PARAMETER)

    def get_active_levels(self):
        return self._send_command_blocking(GET_ACTIVE_LEVELS, NO_PARAMETER, NO_PARAMETER)

    def get_current_states(self):
        return self._send_command_blocking(GET_CURRENT_STATES, NO_PARAMETER, NO_PARAMETER)

    def set_directions(self, new_directions: dict):
        """
        Args:
            new_directions: port number -> True/False

        Returns:
            New input / output directions as 32 bools
        """
        param1 = [i in new_directions for i in range(32)]
        param2 = [new_directions[i] if i in new_directions else False for i in range(32)]
        return self._send_command_blocking(SET_DIRECTIONS, encode_parameter(param1), encode_parameter(param2))

    def set_active_levels(self, new_active_levels: dict):
        """
        Args:
            new_active_levels: port number -> True/False

        Returns:
            New low / high active levels as 32 bools
        """
        param1 = [i in new_active_levels for i in range(32)]
        param2 = [new_active_levels[i] if i in new_active_levels else False for i in range(32)]
        return self._send_command_blocking(SET_ACTIVE_LEVELS, encode_parameter(param1), encode_parameter(param2))

    def set_states(self, new_states: dict):
        """
        Args:
            new_states: port number -> True/False

        Returns:
            New active / inactive states as 32 bools
        """
        param1 = [i in new_states for i in range(32)]
        param2 = [new_states[i] if i in new_states else False for i in range(32)]
        return self._send_command_blocking(SET_CURRENT_STATES, encode_parameter(param1), encode_parameter(param2))
