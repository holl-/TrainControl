import math
import time

import tkinter as tk
import tkinter.ttk as ttk
from threading import Thread

from winrawin import hook_raw_input_for_window, RawInputEvent, list_devices, Mouse, Keyboard
from . import hid

from .train_def import Train, CONTROLS
from .train_control import TrainControl


class TKGUI:

    def __init__(self, control: TrainControl, info=None):
        self.control = control
        self.window = tk.Tk()
        self.last_events = {}  # device_path -> RawInputEvent
        self.device_labels = {}  # device_path -> (label, ...)
        self.window.title("Device Monitoring")
        self.window.geometry('640x600')
        self.missing_devices = []  # device_path
        self.speed_bars = {}  # train -> ProgressBar

        if info:
            tk.Label(text=info, font='Helvetica 12').pack()
        tk.Label(text="Signal generators", font='Helvetica 14 bold').pack()

        status_pane = tk.Frame(self.window)
        status_pane.pack()
        self.status_labels = {}  # port -> Label
        for i, port in enumerate(control.generator.get_open_ports()):
            port_label = tk.Label(status_pane, text=port or '<Debug>')
            port_label.grid(row=i, column=0)
            status_label = tk.Label(status_pane, text="unknown")
            status_label.grid(row=i, column=1)
            self.status_labels[port] = status_label

        tk.Label(text="Controls", font='Helvetica 14 bold').pack()
        controls_pane = tk.Frame(self.window)
        controls_pane.pack()
        self.last_action_labels = {}
        row = 0
        def add_progress_bar(train: Train):
            progress_bar = ttk.Progressbar(controls_pane, value=50, length=100)
            progress_bar.grid(row=row, column=3)
            self.speed_bars[train] = progress_bar
        for device_path, train in CONTROLS.items():
            try:
                hid_device = hid.Device(path=bytes(device_path, 'ascii'))
                device_name = hid_device.product
                manufacturer = hid_device.manufacturer
            except:
                device_name = "..." + device_path[-20:]
                manufacturer = ''
                self.missing_devices.append(device_path)
            manufacturer_label = tk.Label(controls_pane, text=manufacturer)
            manufacturer_label.grid(row=row, column=0)
            device_label = tk.Label(controls_pane, text=device_name)
            device_label.grid(row=row, column=1)
            self.device_labels[device_path] = (manufacturer_label, device_label)
            tk.Label(controls_pane, text=train.name).grid(row=row, column=2)
            if train in control.trains:
                add_progress_bar(train)
            else:
                tk.Label(controls_pane, text="not managed").grid(row=row, column=3)
            last_action_label = tk.Label(controls_pane, text='nothing')
            last_action_label.grid(row=row, column=4)
            last_action_label.config(width=9, height=2)
            self.last_action_labels[device_path] = last_action_label
            row += 1
        for train in control.trains:
            if train not in CONTROLS.values():
                tk.Label(controls_pane, text=train.name).grid(row=row, column=2)
                add_progress_bar(train)
                row += 1

        tk.Label(text="Press F11 to enter fullscreen mode").pack()

        # fullscreen_button = tk.Button(text='Fullscreen', command=lambda: self.window.attributes("-fullscreen", not self.window.attributes('-fullscreen')))
        # fullscreen_button.pack()
        self.window.bind("<F11>", lambda e: self.window.attributes("-fullscreen", not self.window.attributes('-fullscreen')))
        self.window.bind("<Escape>", lambda e: control.terminate())
        self.window.protocol("WM_DELETE_WINDOW", lambda: control.terminate())

        hook_raw_input_for_window(self.window.winfo_id(), self.process_event)

    def launch(self):
        self.window.after(10, self.update_ui)
        self.window.mainloop()

    def process_event(self, e: RawInputEvent):
        if e.device.name not in CONTROLS:
            return
        if e.device.name in self.missing_devices:
            self.missing_devices.remove(e.device.name)
            manufacturer_label, device_label = self.device_labels[e.device.name]
            try:
                hid_device = hid.Device(path=bytes(e.device.name, 'ascii'))
                manufacturer_label.config(text=hid_device.manufacturer)
                device_label.config(text=hid_device.product)
            except:
                pass
        self.last_events[e.device.name] = e
        train = CONTROLS[e.device.name]
        control_train(self.control, train, e)

    def update_ui(self):
        for device, event in self.last_events.items():
            label = self.last_action_labels[device]
            if not event.device.is_connected():
                label.config(text='disconnected', bg=tk_rgb(255, 0, 0))
            else:
                last = time.perf_counter() - event.time
                fac = 1 - math.exp(-last)
                label.config(text=event_summary(event), bg=tk_rgb(int(255 * fac), 255, int(255 * fac)))
        for train in self.control.trains:
            self.speed_bars[train].config(value=abs(100 * (self.control.get_speed(train) or 0.) / train.max_speed))
        for port in self.control.generator.get_open_ports():
            error = self.control.generator.get_error(port)
            if port is None:
                signal_status = "⛔ No signal on debug port"
            elif error:
                signal_status = f"⛔ {error}"
            elif self.control.generator.is_short_circuited(port):
                signal_status = '⚠ short-circuited or no power'
            elif self.control.generator.is_sending_on(port):
                signal_status = '✅'
            else:
                signal_status = '⚠'
            self.status_labels[port].config(text=signal_status)
        self.window.after(10, self.update_ui)


def tk_rgb(r, g, b):
    return "#%02x%02x%02x" % (r, g, b)


def event_summary(e: RawInputEvent):
    if e.event_type in ('up', 'down'):
        return f"{e.name} {e.event_type}"
    elif e.event_type == 'move':
        return f"({e.delta_x}, {e.delta_y})"
    else:
        return e.event_type


def control_train(control: TrainControl, train: Train, event: RawInputEvent):
    if event.device_type == 'keyboard':
        if event.event_type == 'down' and event.name == 'up':
            control.set_acceleration_control(train, 1.)
        elif event.event_type == 'down' and event.name == 'down':
            control.set_acceleration_control(train, -1.)
        elif event.event_type == 'up':
            control.set_acceleration_control(train, 0)
        # ToDo double-click to instantly stop
