import io
import json
import urllib.error

import pytest

from goveehome.protocol import cloud
from goveehome.protocol.cloud import CloudClient, CloudError, parse_state


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def make_opener(reply, log):
    def opener(req, timeout):
        log.append(req)
        if isinstance(reply, Exception):
            raise reply
        return FakeResponse(json.dumps(reply).encode())
    return opener


def test_list_devices_sends_key():
    log = []
    client = CloudClient(" key123 ", opener=make_opener({"code": 200, "data": [{"sku": "H6008"}]}, log))
    assert client.list_devices() == [{"sku": "H6008"}]
    assert log[0].get_header("Govee-api-key") == "key123"
    assert log[0].get_method() == "GET"


def test_color_control_body():
    log = []
    client = CloudClient("k", opener=make_opener({"code": 200}, log))
    client.color("H6008", "AA:BB", (255, 0, 1))
    body = json.loads(log[0].data)
    assert body["payload"]["capability"] == {
        "type": "devices.capabilities.color_setting", "instance": "colorRgb", "value": 0xFF0001}
    assert body["payload"]["device"] == "AA:BB"
    assert body["requestId"]


def test_errors_become_cloud_errors():
    err = urllib.error.HTTPError("u", 401, "nope", {}, None)
    with pytest.raises(CloudError, match="rejected"):
        CloudClient("k", opener=make_opener(err, [])).list_devices()
    with pytest.raises(CloudError, match="bad things"):
        CloudClient("k", opener=make_opener({"code": 400, "message": "bad things"}, [])).list_devices()


def test_parse_state():
    caps = [
        {"instance": "online", "state": {"value": True}},
        {"instance": "powerSwitch", "state": {"value": 1}},
        {"instance": "brightness", "state": {"value": 55}},
        {"instance": "colorRgb", "state": {"value": 0x00FF80}},
        {"instance": "colorTemperatureK", "state": {"value": ""}},
    ]
    assert parse_state(caps) == {"on": True, "brightness": 55, "color": (0, 255, 128)}


def test_scenes():
    reply = {"code": 200, "payload": {"capabilities": [{"instance": "lightScene", "parameters": {
        "options": [{"name": "Sunrise", "value": {"id": 1, "paramId": 2}}, {"broken": True}]}}]}}
    scenes = CloudClient("k", opener=make_opener(reply, [])).scenes("H6008", "AA")
    assert scenes == [{"name": "Sunrise", "value": {"id": 1, "paramId": 2}, "instance": "lightScene"}]


CAPS = [
    {"type": "devices.capabilities.segment_color_setting", "instance": "segmentedColorRgb",
     "parameters": {"dataType": "STRUCT", "fields": [
         {"fieldName": "segment", "dataType": "Array", "elementRange": {"min": 0, "max": 14}},
         {"fieldName": "rgb", "dataType": "INTEGER"}]}},
    {"type": "devices.capabilities.music_setting", "instance": "musicMode",
     "parameters": {"dataType": "STRUCT", "fields": [
         {"fieldName": "musicMode", "dataType": "ENUM",
          "options": [{"name": "Energic", "value": 1}, {"name": "Rhythm", "value": 2}]},
         {"fieldName": "sensitivity", "dataType": "INTEGER"}]}},
    {"type": "devices.capabilities.toggle", "instance": "gradientToggle"},
    {"type": "devices.capabilities.toggle", "instance": "fancyThingToggle"},
]


def test_capability_helpers():
    assert cloud.segment_count(CAPS) == 15
    assert cloud.segment_count([]) == 0
    assert cloud.music_modes(CAPS) == [("Energic", 1), ("Rhythm", 2)]
    assert cloud.toggles(CAPS) == [("gradientToggle", "Gradient"), ("fancyThingToggle", "Fancything")]


def test_segment_and_music_bodies():
    log = []
    client = CloudClient("k", opener=make_opener({"code": 200}, log))
    client.segment_color("H619A", "AA", [3, 1], (0, 0, 255))
    client.music_mode("H619A", "AA", 2, 150)
    client.set_scene("H619A", "AA", {"id": 5}, "diyScene")
    caps = [json.loads(r.data)["payload"]["capability"] for r in log]
    assert caps[0] == {"type": cloud.CAP_SEGMENT, "instance": "segmentedColorRgb",
                       "value": {"segment": [1, 3], "rgb": 255}}
    assert caps[1]["value"] == {"musicMode": 2, "sensitivity": 100}
    assert caps[2]["instance"] == "diyScene"
