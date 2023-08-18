import threading
import time
from typing import Callable


def schedule_at_fixed_rate(task_function: Callable, period: float):
    """
    Seems like 'schedule' is not precise enough and 'apscheduler' just looks terrible. Threading does not have this function.

    Args:
        task_function: function to call, single parameter `dt`
        period: seconds between calls
    """
    def run():
        i = 0
        t0 = time.time()
        t = t0
        while True:
            ti = time.time()
            task_function(ti - t)
            t = ti
            i += 1
            delta = t0 + period * i - time.time()
            if delta > 0:
                time.sleep(delta)

    threading.Thread(target=run, name=f'Schedule {task_function.__name__}').start()


def fit_image_size(img_res, max_width, max_height):
    image_aspect = img_res[0] / img_res[1]
    max_aspect = max_width / max_height
    if image_aspect > max_aspect:  # wide image: fit width
        return max_width, int(round(img_res[1] * max_width / img_res[0]))
    else:  # narrow image: fit height
        return int(round(img_res[0] * max_height / img_res[1])), max_height
