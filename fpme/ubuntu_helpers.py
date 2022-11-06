import datetime
import subprocess
import time


def pc_has_power():
    try:
        result = subprocess.check_output(['acpi', '-a'])
    except FileNotFoundError:
        return True
    if b'off-line' in result:
        return False
    if b'on-line' in result:
        return True
    raise OSError(result)


def set_wake_time(unix_time_sec: int, shutdown_now: bool):
    subprocess.run(['rtcwake', '-l', '-m', 'off' if shutdown_now else 'no', '-t', str(unix_time_sec)])


def tomorrow_at(hour=12, minute=55):
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    local_time = datetime.time(hour=hour, minute=minute)
    local_datetime = datetime.datetime.combine(tomorrow, local_time)
    return int(time.mktime(local_datetime.timetuple()))


# print(tomorrow_at(12, 55))
