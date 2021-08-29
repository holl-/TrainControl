

def get_possible_arrival_platforms(from_track: str) -> tuple:
    if from_track in 'AB':
        return 2,
    elif from_track in 'CD':
        return 2, 3


def get_possible_departure_tracks(from_platform: int) -> str:
    if from_platform == 1:
        return 'ABCD'
    elif from_platform == 2:
        return 'BCD'
    elif from_platform == 3:
        return 'CD'
