from goveehome.protocol import razer


def test_enable_frames_match_known_packets():
    assert razer.encode(razer.enable_frame(True)) == "uwABsQEK"
    assert razer.encode(razer.enable_frame(False)) == "uwABsQAL"


def test_color_frame_layout():
    frame = razer.color_frame([(255, 0, 0), (0, 255, 0)], gradient=True)
    assert frame[:6] == bytes([0xBB, 0x00, 8, 0xB0, 0x01, 2])
    assert frame[6:12] == bytes([255, 0, 0, 0, 255, 0])
    assert razer.checksum(frame[:-1]) == frame[-1]


def test_color_frame_clamps_and_limits():
    colors = [(300, -5, 12.6)] * 200
    frame = razer.color_frame(colors)
    assert frame[5] == razer.MAX_SEGMENTS
    assert frame[6:9] == bytes([255, 0, 13])
    assert frame[2] == razer.MAX_SEGMENTS * 3 + 2 <= 255


def test_round_trip():
    frame = razer.color_frame([(1, 2, 3)])
    assert razer.decode(razer.encode(frame)) == frame
