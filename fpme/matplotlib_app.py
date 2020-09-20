import matplotlib.pyplot as plt
from matplotlib.widgets import Button

from fpme import trains, drivers


TRAIN_NAMES = list(sorted(trains.TRAINS.keys()))

fig, ax = plt.subplots()
fig.canvas.set_window_title('Modelleisenbahn Steuerung')
plt.subplots_adjust(bottom=0.2)
b = plt.bar(range(1 + len(TRAIN_NAMES)), [0] * (1 + len(TRAIN_NAMES)),
            color=['red'] + ['gray'] * len(TRAIN_NAMES),
            width=[0.9] + [0.5] * len(TRAIN_NAMES),
            tick_label=['Power'] + TRAIN_NAMES)
plt.xticks(rotation=15)
plt.ylim((0, 1.05))


def update():
    power = trains.is_power_on()
    b.patches[0].set_height(0.5 * b.patches[0].get_height() + 0.5 * power)
    for i, name in enumerate(TRAIN_NAMES):
        set_train_speed(b.patches[i+1], trains.TRAINS[name].speed, power)


def set_train_speed(rectangle, speed, power):
    rectangle.set_height(0.5 * rectangle.get_height() + 0.5 * abs(speed))
    if speed != 0:
        rectangle.set_color(('green' if speed > 0 else 'blue') if power else 'gray')


def start(_event):
    trains.start()
    update()
    plt.draw()


def stop(_event):
    if trains.is_power_on():
        trains.stop()
    else:
        for train in trains.TRAINS.values():
            train.stop()
    update()
    plt.draw()


y = 0.02
start_button = Button(plt.axes([0.81, y, 0.1, 0.075]), 'Start')
start_button.on_clicked(start)
stop_button = Button(plt.axes([0.7, y, 0.1, 0.075]), 'Stop')
stop_button.on_clicked(stop)
normal_drivers = Button(plt.axes([0.1, y, 0.2, 0.075]), 'Normal drivers')
normal_drivers.on_clicked(lambda _: drivers.load_train_drivers())
switch_drivers = Button(plt.axes([0.31, y, 0.1, 0.075]), 'Switch')
switch_drivers.on_clicked(lambda _: drivers.switch_drivers())


def show():
    while True:
        update()
        plt.pause(0.05)


if __name__ == '__main__':
    show()

