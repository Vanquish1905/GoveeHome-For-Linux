import json
import socket
import threading
import time

import pytest

from goveehome.protocol import lan


def test_messages_are_compact_json():
    msg = json.loads(lan.color_message((255, 128, 0)))
    assert msg == {"msg": {"cmd": "colorwc", "data": {"color": {"r": 255, "g": 128, "b": 0},
                                                      "colorTemInKelvin": 0}}}
    assert b" " not in lan.turn_message(True)


def test_brightness_and_kelvin_are_clamped():
    assert json.loads(lan.brightness_message(0))["msg"]["data"]["value"] == 1
    assert json.loads(lan.brightness_message(250))["msg"]["data"]["value"] == 100
    assert json.loads(lan.kelvin_message(12000))["msg"]["data"]["colorTemInKelvin"] == 9000


def test_parse_message_rejects_garbage():
    assert lan.parse_message(b"not json") is None
    assert lan.parse_message(b'{"foo": 1}') is None
    assert lan.parse_message(lan.status_message()) == ("devStatus", {})


def test_parse_status():
    state = lan.parse_status({"onOff": 1, "brightness": 42, "color": {"r": 1, "g": 2, "b": 3},
                              "colorTemInKelvin": 0})
    assert state == {"on": True, "brightness": 42, "color": (1, 2, 3), "kelvin": 0}


def _free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


@pytest.mark.skipif(not (_free(4001) and _free(4003) and _free(4002)), reason="Govee ports busy")
def test_client_talks_to_a_light():
    """Full round trip against a tiny fake light on localhost."""
    received = []
    stop = threading.Event()

    def light():
        scan = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        scan.bind(("127.0.0.1", 4001))
        ctrl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ctrl.bind(("127.0.0.1", 4003))
        for s in (scan, ctrl):
            s.settimeout(0.1)
        while not stop.is_set():
            for s in (scan, ctrl):
                try:
                    data, (host, _) = s.recvfrom(4096)
                except socket.timeout:
                    continue
                cmd, _payload = lan.parse_message(data)
                received.append(cmd)
                if cmd == "scan":
                    reply = {"ip": "127.0.0.1", "device": "AA:BB", "sku": "H6199"}
                elif cmd == "devStatus":
                    reply = {"onOff": 1, "brightness": 50, "color": {"r": 9, "g": 8, "b": 7}}
                else:
                    continue
                s.sendto(lan.build_message(cmd, reply), (host, lan.LISTEN_PORT))
        scan.close()
        ctrl.close()

    thread = threading.Thread(target=light, daemon=True)
    thread.start()
    found, statuses = [], []
    client = lan.LanClient(on_scan=found.append, on_status=lambda ip, d: statuses.append((ip, d)))
    assert client.start()
    try:
        client.scan(["127.0.0.1"])
        deadline = time.time() + 3
        while not found and time.time() < deadline:
            time.sleep(0.05)
        assert found and found[0]["sku"] == "H6199"
        client.request_status("127.0.0.1")
        client.stream_colors("127.0.0.1", [(1, 2, 3)])
        deadline = time.time() + 3
        while not statuses and time.time() < deadline:
            time.sleep(0.05)
        assert statuses[0][1]["brightness"] == 50
        time.sleep(0.2)
        assert "razer" in received
    finally:
        stop.set()
        client.stop()
        thread.join(2)
