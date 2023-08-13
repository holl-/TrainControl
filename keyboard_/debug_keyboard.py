import keyboard
from keyboard import KeyboardEvent

print(keyboard.__file__)

def on_press2(event: KeyboardEvent):
    print(event, 'received from', event.device)


keyboard.on_press(on_press2)  # keyboard.hook(on_press)
keyboard.wait()
print("Exit")
