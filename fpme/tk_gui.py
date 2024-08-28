import math
import time
import tkinter as tk
import tkinter.ttk as ttk
from typing import Dict, List

from PIL import ImageTk

from .helper import fit_image_size
from .hid_input import InputManager, CONTROLS
from .signal_gen import list_com_ports
from .switches import SwitchManager
from .train_control import TrainControl
from .train_def import Train


class TKGUI:

    def __init__(self, control: TrainControl, switches: SwitchManager, inputs: InputManager, infos=(), fullscreen=False):
        self.control = control
        self.switches = switches
        self.inputs = inputs
        self.window = tk.Tk()
        self.speed_bars: Dict[Train, ttk.Progressbar] = {}
        self.direction_labels: Dict[Train, tk.Label] = {}
        self.active_vars: Dict[Train, tk.IntVar] = {}
        self.shown_trains: List[Train] = []

        self.window.title("Device Monitoring")
        self.window.geometry('640x600')
        if fullscreen:
            self.window.attributes("-fullscreen", True)

        for info in infos:
            tk.Label(text=info).pack()
        tk.Label(text="Hardware", font='Helvetica 14 bold').pack()

        status_pane = tk.Frame(self.window)
        status_pane.pack()
        self.status_labels = {}  # port -> Label
        row = 0
        port_descriptions = {port: desc for port, desc, hwid in list_com_ports(include_bluetooth=True)}
        for port in control.generator.get_open_ports():
            tk.Label(status_pane, text=port).grid(row=row, column=0)
            tk.Label(status_pane, text=port_descriptions.get(port, 'Fake port')).grid(row=row, column=1)
            status_label = tk.Label(status_pane, text="unknown")
            status_label.grid(row=row, column=2)
            self.status_labels[port] = status_label
            row += 1
        for device in switches.get_devices():
            tk.Label(status_pane, text=device).grid(row=row, column=0)
            tk.Label(status_pane, text="USB switch control").grid(row=row, column=1)
            status_label = tk.Label(status_pane, text="unknown")
            status_label.grid(row=row, column=2)
            self.status_labels[device] = status_label
            row += 1

        tk.Label(text="Controls", font='Helvetica 14 bold').pack()
        controls_pane = tk.Frame(self.window)
        controls_pane.pack()
        self.last_action_labels = {}
        self.photos = []
        row = 0
        def add_progress_bar(train: Train):
            progress_bar = ttk.Progressbar(controls_pane, value=50, length=100)
            progress_bar.grid(row=row, column=4)
            self.speed_bars[train] = progress_bar
            direction_label = tk.Label(controls_pane, text='')
            direction_label.grid(row=row, column=5)
            self.direction_labels[train] = direction_label
        for device_path, train in CONTROLS.items():
            self.shown_trains.append(train)
            self.active_vars[train] = is_active = tk.IntVar(value=1)
            active = tk.Checkbutton(controls_pane, text=f"{row+1}", variable=is_active)
            active.grid(row=row, column=3)
            photo = ImageTk.PhotoImage(train.image.resize(fit_image_size(train.img_res, 80, 30)))
            self.photos.append(photo)
            tk.Label(controls_pane, text=train.name, image=photo, compound=tk.LEFT).grid(row=row, column=2)
            if train in control.trains:
                add_progress_bar(train)
            else:
                tk.Label(controls_pane, text="not managed").grid(row=row, column=3)
            last_action_label = tk.Label(controls_pane, text='nothing')
            last_action_label.grid(row=row, column=6)
            last_action_label.config(width=9, height=2)
            self.last_action_labels[device_path] = last_action_label
            row += 1
        for train in control.trains:
            if train not in CONTROLS.values():
                tk.Label(controls_pane, text=train.name).grid(row=row, column=2)
                add_progress_bar(train)
                row += 1
                self.shown_trains.append(train)
        # --- Status ---
        tk.Label(text="Status (P/R)", font='Helvetica 14 bold').pack()
        status_pane = tk.Frame(self.window)
        status_pane.pack()
        tk.Label(status_pane, text="Status (P/R)").grid(row=0, column=0)
        self.active_status = tk.Label(status_pane, text="...")
        self.active_status.grid(row=0, column=1)
        tk.Label(status_pane, text="Light (F2/F3)").grid(row=1, column=0)
        self.light_status = tk.Label(status_pane, text="...")
        self.light_status.grid(row=1, column=1)
        tk.Label(status_pane, text="Sound (F6/F7)").grid(row=2, column=0)
        self.sound_status = tk.Label(status_pane, text="...")
        self.sound_status.grid(row=2, column=1)
        tk.Label(status_pane, text="Limit (+/-)").grid(row=3, column=0)
        self.speed_limit = tk.Label(status_pane, text="...")
        self.speed_limit.grid(row=3, column=1)
        # --- Status highlights ---
        event_pane = tk.Frame(self.window)
        event_pane.pack()
        self.emergency_break_all_highlight = tk.Label(event_pane, text="")
        self.emergency_break_all_highlight.grid(row=0, column=0)
        self.power_off_highlight = tk.Label(event_pane, text="Power off")
        self.power_off_highlight.grid(row=0, column=1)
        self.power_on_highlight = tk.Label(event_pane, text="Power on")
        self.power_on_highlight.grid(row=0, column=2)
        # --- Hotkeys ---
        tk.Label(text="Press F11 to enter fullscreen mode").pack()
        self.window.bind("<F11>", lambda e: self.window.attributes("-fullscreen", not self.window.attributes('-fullscreen')))
        self.window.bind("<F2>", lambda e: self.control.set_lights_on(False))
        self.window.bind("<F3>", lambda e: self.control.set_lights_on(True))
        self.window.bind("<F6>", lambda e: self.control.set_sound_on(False))
        self.window.bind("<F7>", lambda e: self.control.set_sound_on(True))
        self.window.bind("<p>", lambda e: self.control.pause())
        self.window.bind("<r>", lambda e: self.control.resume())
        self.window.bind("<+>", lambda e: self.control.set_global_speed_limit(None if self.control.speed_limit is None else (self.control.speed_limit + 20 if self.control.speed_limit < 240 else None)))
        self.window.bind("<minus>", lambda e: self.control.set_global_speed_limit(240 if self.control.speed_limit is None else self.control.speed_limit - 20))
        self.window.bind("<Escape>", lambda e: control.terminate())
        self.window.bind("1", lambda e: self.toggle_active(0))
        self.window.bind("2", lambda e: self.toggle_active(1))
        self.window.bind("3", lambda e: self.toggle_active(2))
        self.window.bind("4", lambda e: self.toggle_active(3))
        self.window.bind("5", lambda e: self.toggle_active(4))
        self.window.bind("6", lambda e: self.toggle_active(5))
        self.window.bind("7", lambda e: self.toggle_active(6))
        self.window.bind("8", lambda e: self.toggle_active(7))
        self.window.bind("9", lambda e: self.toggle_active(8))
        self.window.bind("0", lambda e: self.toggle_active(9))
        self.window.protocol("WM_DELETE_WINDOW", lambda: control.terminate())

    def launch(self):
        self.window.after(10, self.update_ui)
        self.window.mainloop()

    def update_ui(self):
        now = time.perf_counter()
        # --- Highlight recent inputs and detect disconnected devices ---
        for device, (t, text) in self.inputs.last_events.items():
            if device in self.last_action_labels:
                label = self.last_action_labels[device]
                if device in self.inputs.disconnected:
                    label.config(text='disconnected', bg=tk_rgb(255, 0, 0))
                    train = CONTROLS[device]
                    self.control.deactivate(train, device)
                else:
                    fac = 1 - math.exp(t - now)
                    label.config(text=text, bg=tk_rgb(int(255 * fac), 255, int(255 * fac)))
        # -- Highlight recent global commands ---
        cause_text = lambda x: CONTROLS[x].name if x in CONTROLS else x
        fac = 1 - math.exp(self.control.last_emergency_break_all[0] - now)
        self.emergency_break_all_highlight.config(text=f"Emergency all: {cause_text(self.control.last_emergency_break_all[1])}", bg=tk_rgb(255, int(255 * fac), int(255 * fac)))
        fac = 1 - math.exp(self.control.last_power_off[0] - now)
        self.power_off_highlight.config(text=f"Power off: {cause_text(self.control.last_power_off[1])}", bg=tk_rgb(255, int(255 * fac), int(255 * fac)))
        fac = 1 - math.exp(self.control.last_power_on[0] - now)
        self.power_on_highlight.config(text=f"Power on: {cause_text(self.control.last_power_on[1])}", bg=tk_rgb(int(255 * fac), 255, int(255 * fac)))
        # --- Update train display ---
        for train in self.control.trains:
            self.speed_bars[train].config(value=abs(100 * (self.control.get_speed(train) or 0.) / train.max_speed))
            self.direction_labels[train].config(text='🡄' if self.control.is_in_reverse(train) else '🡆')
        for train, var in self.active_vars.items():
            if bool(var.get()) != self.control.is_active(train):
                var.set(int(self.control.is_active(train)))
        # --- Update status displays ---
        for port in self.control.generator.get_open_ports():
            error = self.control.generator.get_error(port)
            if error:
                signal_status = f"⛔ {error}"
            elif self.control.generator.is_short_circuited(port):
                signal_status = "⚠ short-circuited or no power"
            elif self.control.generator.is_sending_on(port):
                signal_status = "✅"
            elif self.control.paused:
                signal_status = "paused"
            else:
                signal_status = "⚠"
            self.status_labels[port].config(text=signal_status)
        for device in self.switches.get_devices():
            error = self.switches.get_error(device)
            switch_status = f"⛔ {error}" if error else "✅"
            self.status_labels[device].config(text=switch_status)
        self.active_status.config(text="paused" if self.control.paused else "not paused")
        self.light_status.config(text="on" if self.control.light else ("?" if self.control.light is None else "off"))
        self.sound_status.config(text="on" if self.control.sound else ("?" if self.control.sound is None else "off"))
        self.speed_limit.config(text=str(self.control.speed_limit))
        # --- Schedule next update ---
        self.window.after(10, self.update_ui)

    def toggle_active(self, train_id: int):
        if train_id >= len(self.shown_trains):
            return
        train = self.shown_trains[train_id]
        is_active = self.control.is_active(train)
        if is_active:
            self.control.deactivate(train, None)
        else:
            self.control.activate(train, None)


def tk_rgb(r, g, b):
    return "#%02x%02x%02x" % (r, g, b)
