import math
import time

import tkinter as tk

from fpme.hid_input import InputManager


def tk_rgb(r, g, b):
    return "#%02x%02x%02x" % (r, g, b)


def open_window():
    window = tk.Tk()
    window.title("Device Monitoring")
    window.geometry('640x600')

    def create_copiable_label(parent, text, copy_str: str, **kwargs):
        def copy(_event):
            window.clipboard_clear()
            window.clipboard_append(text.replace("\\", "\\\\"))
            print(f"Copied to clipboard: {copy_str}")

        label = tk.Label(parent, text=text[:90], **kwargs)
        label.bind("<Button-1>", copy)
        return label

    label_info = tk.Label(text="Click on an entry to copy the hardware ID to the clipboard.")
    label_info.pack()

    table = tk.Frame(window)
    table.pack()

    def update_ui():
        for widget in table.winfo_children():
            widget.destroy()
        for path in tuple(inputs.connected):
            t, text = inputs.last_events[path]
            fac = 1 - math.exp(t - time.perf_counter())
            label = create_copiable_label(table, text=text+" "+path, copy_str=path.replace('\\', '\\\\'), bg=tk_rgb(0, 0, 0))
            label.config(bg=tk_rgb(int(255 * fac), 255, int(255 * fac)))
            label.pack()
        for path in tuple(inputs.disconnected):
            label = create_copiable_label(table, text=path, copy_str=path.replace('\\', '\\\\'), bg=tk_rgb(0, 0, 0))
            label.config(bg=tk_rgb(255, 0, 0))
            label.pack()
        window.after(10, update_ui)

    window.after(10, update_ui)
    window.mainloop()


if __name__ == '__main__':
    inputs = InputManager(None)
    inputs.start_detection()
    open_window()


# \\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}&Dev&VID_045e&PID_0b13&REV_0509&0c352633ee04&IG_00#a&3724ae32&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}', vendor_id=1118, product_id=2835, version_number=1289, usage_page=1, usage_page_name='Generic Desktop Controls', usage=5, usage_name='Game Pad')
