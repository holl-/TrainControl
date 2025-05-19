import pygame

pygame.mixer.init()

def play_background_loop(file: str):
    pygame.mixer.music.load(file)
    pygame.mixer.music.play(loops=-1)  # infinite loop


def async_play(file: str, left_vol=1., right_vol=1.):
    sound = pygame.mixer.Sound(file)
    channel = pygame.mixer.find_channel()
    channel.set_volume(left_vol, right_vol)  # Left speaker only
    channel.play(sound)

