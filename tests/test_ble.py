from goveehome.protocol import ble


def _check(packet):
    assert len(packet) == 20
    x = 0
    for b in packet[:-1]:
        x ^= b
    assert x == packet[-1]


def test_power_packet():
    p = ble.power_packet(True)
    _check(p)
    assert p[:3] == bytes([0x33, 0x01, 0x01])


def test_brightness_scaled_to_byte():
    p = ble.brightness_packet(100)
    _check(p)
    assert p[2] == 255
    assert ble.brightness_packet(0)[2] == 0


def test_color_modes():
    old = ble.color_packet((10, 20, 30), 0x02)
    new = ble.color_packet((10, 20, 30), 0x0D)
    seg = ble.color_packet((10, 20, 30), 0x15)
    for p in (old, new, seg):
        _check(p)
    assert old[2:6] == bytes([0x02, 10, 20, 30])
    assert new[2:6] == bytes([0x0D, 10, 20, 30])
    assert seg[2:7] == bytes([0x15, 0x01, 10, 20, 30])


def test_keepalive_is_well_known_value():
    assert ble.keepalive_packet().hex() == "aa01" + "00" * 17 + "ab"


def test_name_helpers():
    assert ble.looks_like_govee("ihoment_H6199_1A2B")
    assert not ble.looks_like_govee("JBL Flip 5")
    assert not ble.looks_like_govee(None)
    assert ble.sku_from_name("ihoment_H6199_1A2B") == "H6199"
    assert ble.sku_from_name("Govee_h6008_ABCD") == "H6008"
