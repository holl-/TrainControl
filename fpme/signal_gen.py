import time

import serial

ser = serial.Serial(
    port='COM1',
    baudrate=38400,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    bytesize=serial.SIXBITS
)

ser.is_open or ser.open()
assert ser.is_open


ZERO = (63, 63)  # 416 ms pause
ONE = (0, 0)
OPEN = (0, 63)

# ternary encoding (0, 1, 2/open)
addr_60 = (*ZERO, *OPEN, *ZERO, *OPEN)  # 60, ICE
addr_24 = (*ZERO, *OPEN, *OPEN, *ZERO)  # 24, E-Lok (DB)
addr_1 = (*ONE, *ZERO, *ZERO, *ZERO)  # 72, E-Lok (BW)
addr_78 = (*ZERO, *OPEN, *OPEN, *OPEN)  # 78, Dampf
addr_72 = (*ZERO, *ZERO, *OPEN, *OPEN)  # 72, Diesel
addr_21 = (*ZERO, *ONE, *OPEN, *ZERO)  # 21, S-Bahn


def address_to_bytes(address: int):
    return {
        1: addr_1,
        21: addr_21,
        24: addr_24,
        60: addr_60,
        72: addr_72,
        78: addr_78,
    }[address]


def all_addresses():
    result = []
    for bit1 in (ZERO, ONE, OPEN):
        for bit2 in (ZERO, ONE, OPEN):
            for bit3 in (ZERO, ONE, OPEN):
                for bit4 in (ZERO, ONE, OPEN):
                    result.append(bit1 + bit2 + bit3 + bit4)
    return result


def bool_to_bytes(bool):
    return ONE if bool else ZERO


def int4_to_bytes(number):
    return bool_to_bytes(number & 1) + bool_to_bytes((number >> 1) & 1) + bool_to_bytes((number >> 2) & 1) + bool_to_bytes(number >> 3)


def packet(address, func=False, speed=0):  # speed=1 Richtungswechsel
    packet = address
    packet += ONE if func else ZERO
    packet += int4_to_bytes(speed)
    return bytes(packet)


def scan_all():
    for addr in all_addresses()[15:17]:
        print(addr)
        for cycle in range(5000):
            ser.write(packet(addr, True, 8))
            time.sleep(9 * 416e-6)
            time.sleep(1250e-6)  # 3 t-bits pause between signals


while True:
    ser.write(packet(addr_78, True, 6))
    time.sleep(9 * 416e-6)  # packet is 9 t-bits long (18 bytes)
    time.sleep(1250e-6)  # 3 t-bits pause between signals
