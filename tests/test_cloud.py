import io
import json
import urllib.error

import pytest

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
    assert scenes == [{"name": "Sunrise", "value": {"id": 1, "paramId": 2}}]
