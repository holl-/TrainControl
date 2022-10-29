
LENGTHS = {
    # Curved
    115: 94.2,
    130: 188.5,
    206: 43.5,  # 5.7°
    224: 185.5,  # 24.3°
    230: 229.1,
    330: 269.6,
    430: 303.3,
    530: 337.0,
    # Straight
    64: 64.3,
    71: 70.8,
    77: 77.5,
    94: 94.2,
    172: 171.7,
    188: 188.3,
    229: 229.3,
    236: 236.1,
    360: 360,
    # Switches
    # 611: ,  # 24188 and 24224
    # 612: ,  # 24188 and 24224
    671: 266,  # Curved, use this only for the outer radius, inner = 24130, outer = 24130+24077
    672: 266,  # 188.5 + 77.5
}

def compute_length(tracks: str or tuple or list):
    if isinstance(tracks, str):
        tracks = [s.strip() for s in tracks.split(',') if s.strip()]
    length = 0
    for track in tracks:
        if track.startswith('24'):
            track = track[2:]
        length += LENGTHS[int(track)]
    return length


# inner = compute_length("""
# 224, 206,
# 230, 130, 330, 330, 230, 230, 130,
# 130, 130, 130,
# 172, 094, 172, 130, 130,
# 188, 172, 130, 188, 188,
# """)
# print(f"Inner: {inner}")

# outer = compute_length("""
# 188, 188, 230, 172, 188,
# 230, 230, 172, 094, 188,
# 230, 230, 230,
# 188, 172, 188,
# 230, 330, 188, 430,
# 094, 188, 172, 130, 130, 672
# """)
# print(f"Outer: {outer}")

# inner_connection = compute_length('130, 130, 130')
# print(f"Inner connection: {inner_connection}")
#
# outer_connection = compute_length('130, 130, 671')
# print(f"Outer connection: {outer_connection}")
#
# interim = compute_length("""
# 188, 172,
# 330, 188, 230, 130, 188, 224,
# 24224,
# """)
# print(f"Interim: {interim}")
#
# outer_until_switch = compute_length("""
# 188, 188, 230, 172, 188,
# 230, 230, 172, 094, 188,
# 230, 230, 230,
# """)
# print(f"Outer until switch: {outer_until_switch}")

# i_airport_contact_west = compute_length("""
# 130, 130, 130,
# 188, 172,
# 330, 188, 230, 130,
# """)
# print(f"Interim: {i_airport_contact_west}")

i_contact = compute_length("""
130, 130, 672,
""")
print(f"Interim: {i_contact}")