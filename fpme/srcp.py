"""
Simple Railroad Command Protocol

http://www.der-moba.de/index.php/SRCP-Grundlagen

v 0.7.3
"""

import socket

CMD_SOCKET = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
CMD_SOCKET.connect(('localhost', 4303))

print(CMD_SOCKET.recv(1024))
CMD_SOCKET.sendall(b"SET PROTOCOL SRCP 0.8.2")
CMD_SOCKET.sendall(b"GO")
CMD_SOCKET.sendall(b"GET 0 GL 1")
print(CMD_SOCKET.recv(1024))


def send(addr: int, speed: float or None, func=False):
    """
    Set locomotive state.

    :param addr: train address
    :param speed: float in the range [-1, 1] or None for emergency stop
    :param func: whether primary train function is active
    """
    if CMD_SOCKET is None:
        return False
    direction = 2 if speed is None else (0 if speed < 0 else 1)
    speed = abs(int(round(speed * 100)))
    func = int(func)
    CMD_SOCKET.send(bytes(f"SET GL M2 {addr} {direction} {speed} 100 {func} 0".encode("utf-8")))
    return True
    # data = s.recv(BUFFER_SIZE)


def disconnect():
    if CMD_SOCKET is None:
        return False
    CMD_SOCKET.send(b"LOGOUT")
    CMD_SOCKET.close()


def shutdown():
    if CMD_SOCKET is None:
        return False
    CMD_SOCKET.send(b"SHUTDOWN")


def reset():
    if CMD_SOCKET is None:
        return False
    CMD_SOCKET.send(b"RESET")


def set_power(power_on: bool):
    if CMD_SOCKET is None:
        return False
    CMD_SOCKET.send(bytes(f"SET POWER {'ON' if power_on else 'OFF'}".encode("utf-8")))

