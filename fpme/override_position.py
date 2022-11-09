import sys

from fpme import trains, plan_vis
from fpme.museum_control import *

HELP_MESSAGE = """Please specify

1. Train (IGBT or GTO)
2. Which ring the train is on (outer or inner)
3. The position in mm
4. Whether the train is aligned with the track (fwd or bwd or ? to keep previous setting)

Example:
sudo python3 set IGBT inner 1000 fwd"""

GTO, IGBT = read_last_positions()

assert len(sys.argv) == 5, HELP_MESSAGE
train = sys.argv[1]
assert train in ('IGBT', 'GTO'), HELP_MESSAGE
old_state = GTO if train == 'GTO' else IGBT
new_state = State.from_line(" ".join(sys.argv[2:]))
if new_state.aligned is None:
    new_state.aligned = old_state.aligned

if train == 'GTO':
    GTO = new_state
else:
    IGBT = new_state

LOG = create_log_file()
LOG.write(f"{str(GTO)},{str(IGBT)}\n")
LOG.flush()
print("Done. New states:")
print(GTO)
print(IGBT)

plan_vis.show([Controller(trains.get_by_name('GTO'), GTO), Controller(trains.get_by_name('IGBT'), IGBT)], exit_on_close=True)