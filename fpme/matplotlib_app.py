import matplotlib.pyplot as plt
from matplotlib.widgets import Button

from fpme import logic

fig, ax = plt.subplots()
plt.subplots_adjust(bottom=0.2)


def start(_event):
    logic.start()
    plt.draw()


def stop(_event):
    logic.stop()
    plt.draw()


start_button = Button(plt.axes([0.81, 0.05, 0.1, 0.075]), 'Start')
start_button.on_clicked(start)
stop_button = Button(plt.axes([0.7, 0.05, 0.1, 0.075]), 'Stop')
stop_button.on_clicked(stop)
normal_drivers = Button(plt.axes([0.1, 0.05, 0.2, 0.075]), 'Normal drivers')
normal_drivers.on_clicked(lambda _: logic.load_drivers())
switch_drivers = Button(plt.axes([0.31, 0.05, 0.1, 0.075]), 'Switch')
switch_drivers.on_clicked(lambda _: logic.switch_drivers())

if __name__ == '__main__':
    plt.show()

