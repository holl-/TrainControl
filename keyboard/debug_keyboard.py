import keyboard
from keyboard import KeyboardEvent


def on_press(event: KeyboardEvent):
    print(event, 'from', event.device)


keyboard.on_press(on_press)  # keyboard.hook(on_press)
keyboard.wait(hotkey='Esc')
print("Exit")
