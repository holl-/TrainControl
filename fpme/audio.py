from typing import Optional

import sounddevice as sd
from pydub import AudioSegment
import numpy as np
from scipy.signal import convolve


def audio_device_by_name(name: str, api=None):
    for device in sd.query_devices():
        if device['max_output_channels'] > 0 and name in device['name']:
            if api is None or device['hostapi'] == api:
                return device


impulse_response = AudioSegment.from_file("../sound/ansagen/IR_train_station.mp3")
ir_samples = np.array(impulse_response.get_array_of_samples(), dtype=np.float32) / (2**15)
impulse_data = np.reshape(ir_samples, (-1, impulse_response.channels))


def play_audio(file: str, device_index: Optional[int], blocking=True, reverb=False):
    audio = AudioSegment.from_file(file)
    samples = np.array(audio.get_array_of_samples(), dtype=np.float32) / (2**15)
    audio_data = np.reshape(samples, (-1, audio.channels))
    if reverb:
        output_data = np.column_stack([convolve(audio_data[:, ch], impulse_data[:, 0], mode='full') for ch in range(audio.channels)])
        max_val = np.max(abs(output_data))
        if max_val > 1:  # Normalize the output to avoid clipping
            output_data /= max_val
        audio_data = (output_data * (2 ** 15)).astype(np.int16)  # Convert back to 16-bit integer for playback
    sd.play(audio_data, samplerate=audio.frame_rate, device=device_index, blocking=blocking)


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
    play_audio("../sound/ansagen/Gong.mp3", selected_device['index'], reverb=True)
