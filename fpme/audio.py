from typing import Optional

import sounddevice as sd
from pydub import AudioSegment
import numpy as np


def audio_device_by_name(name: str, api=None):
    for device in sd.query_devices():
        if device['max_output_channels'] > 0 and name in device['name']:
            if api is None or device['hostapi'] == api:
                return device


def play_audio(file: str, device_index: Optional[int], blocking=True):
    audio = AudioSegment.from_file(file)
    samples = np.array(audio.get_array_of_samples(), dtype=np.float32) / (2**15)
    data = np.reshape(samples, (-1, audio.channels))
    sd.play(data, samplerate=audio.frame_rate, device=device_index, blocking=blocking)


if __name__ == '__main__':
    devices = sd.query_devices()
    for api in sd.query_hostapis():
        print(api['name'], " ", "Default:", devices[api['default_output_device']]['name'])
        for index in api['devices']:
            device = devices[index]
            if device['max_output_channels'] == 2:  # Filter only output devices
                print('*', device['max_output_channels'], device['name'])

    selected_device = audio_device_by_name("Primary Sound Driver", api=1)
    print(selected_device)
    # selected_device = device_with_name("Piano")['index']
    play_audio("../sound/ansagen/Gong.mp3", selected_device['index'])
