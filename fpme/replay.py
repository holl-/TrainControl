
from fpme import trains
import plan_vis
from fpme.museum_control import *
from museum_track import read_positions



GTO = Controller(trains.get_by_name('GTO'), State(-1, None, NAN, None))
IGBT = Controller(trains.get_by_name('IGBT'), State(-1, None, NAN, None))
TITLE = ""
TIME_DILATION = 4.


def play(log_index: int = None, skip=100):
    time.sleep(1)
    global TITLE
    for i, (title, (state_GTO, state_IGBT)) in enumerate(read_positions(log_index)):
        GTO.state = state_GTO
        IGBT.state = state_IGBT
        print(GTO, IGBT)
        TITLE = title
        if i >= skip:
            time.sleep(2. / TIME_DILATION)


Thread(target=play).start()


plan_vis.show([GTO, IGBT], exit_on_close=True, title_provider=lambda: TITLE)
