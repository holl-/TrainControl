import plan_vis
from fpme.museum_control import *

GTO, IGBT = read_last_positions()
print("GTO:", GTO)
print("IGBT:", IGBT)
plan_vis.show([Controller(trains.get_by_name('GTO'), GTO), Controller(trains.get_by_name('IGBT'), IGBT)], exit_on_close=True)
