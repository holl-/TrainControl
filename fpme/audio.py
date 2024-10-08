import os
from typing import Optional

import sounddevice as sd
from pydub import AudioSegment
import numpy as np
from scipy.signal import convolve
import pyttsx3


engine = pyttsx3.init()


def audio_device_by_name(name: str, api=None):
    for device in sd.query_devices():
        if device['max_output_channels'] > 0 and name in device['name']:
            if api is None or device['hostapi'] == api:
                return device


DIR = os.path.join(os.path.dirname(__file__), "../sound/ansagen/")
impulse_response = AudioSegment.from_file(DIR + "IR_DUBWISE E001 M2S.wav")
ir_samples = np.array(impulse_response.get_array_of_samples(), dtype=np.float32) / (2**15)
impulse_data = np.reshape(ir_samples, (-1, impulse_response.channels))


def apply_reverb(audio_data: np.ndarray):
    output_data = np.column_stack([convolve(audio_data[:, ch], impulse_data[:, 0], mode='full') for ch in range(audio_data.shape[-1])])
    max_val = np.max(abs(output_data))
    if max_val > 1:  # Normalize the output to avoid clipping
        output_data /= max_val
    return (output_data * (2 ** 15)).astype(np.int16)  # Convert back to 16-bit integer for playback


gong = AudioSegment.from_file(DIR + "Gong.mp3")
gong_data = np.reshape(np.array(gong.get_array_of_samples(), dtype=np.float32) / (2**15), (-1, gong.channels))
gong_reverb_data = apply_reverb(gong_data)
gong_duration = 4.


def play_announcement(text: str, device_index: Optional[int] = None):
    # ToDo one process per speaker?
    # sd.play(gong_reverb_data, samplerate=gong.frame_rate, device=device_index, blocking=False)
    voices = engine.getProperty('voices')
    german_voices = [voice for voice in voices if 'German' in voice.name]
    if german_voices:
        engine.setProperty('voice', german_voices[0].id)
    else:
        print("No German voice found. Using default voice.")
    engine.setProperty('rate', 140)  # Speed of speech
    engine.setProperty('volume', 1.0)  # Volume (0.0 to 1.0)
    if not os.path.exists('output'):
        os.makedirs('output')
    file_path = os.path.join(DIR + "ansage.wav")
    engine.save_to_file(text, file_path)
    # time.sleep(gong_duration)
    engine.runAndWait()
    # sd.wait()
    play_audio(file_path, device_index, blocking=True, reverb=True, gong=True)
    sd.wait()


def play_audio(file: str, device_index: Optional[int] = None, blocking=True, reverb=False, gong=False):
    audio = AudioSegment.from_file(file)
    audio_data = np.reshape(np.array(audio.get_array_of_samples(), dtype=np.float32) / (2**15), (-1, audio.channels))
    if gong:
        audio_data = np.concatenate([gong_data[::2, :audio_data.shape[1]], audio_data], 0)
    audio_data = apply_reverb(audio_data) if reverb else audio_data
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
    # play_audio("../sound/ansagen/Gong.mp3", selected_device['index'], reverb=True)
