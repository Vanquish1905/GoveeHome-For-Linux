#!/usr/bin/env python3
"""Pretend to be one or more Govee LAN lights.

Useful for working on the app without real hardware:

    python3 tools/fake_light.py                 # one light on 127.0.0.1
    python3 tools/fake_light.py --count 3       # 127.0.0.1 .. 127.0.0.3

Each fake light answers discovery, keeps its own state, answers devStatus
and prints what it receives (including decoded streaming frames).
"""

from __future__ import annotations

import argparse
import base64
import json
import socket
import struct
import threading

GROUP = "239.255.255.250"
SKUS = ["H6199", "H6076", "H6008", "H61A0"]


class FakeLight:
    def __init__(self, index: int, ip: str, quiet: bool):
        self.ip = ip
        self.sku = SKUS[index % len(SKUS)]
        self.device = "AA:BB:CC:DD:EE:FF:00:{:02X}".format(index + 1)
        self.quiet = quiet
        self.state = {"onOff": 1, "brightness": 80, "color": {"r": 255, "g": 140, "b": 40},
                      "colorTemInKelvin": 0}
        self.ctrl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ctrl.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ctrl.bind((ip, 4003))

    def log(self, text):
        if not self.quiet:
            print(f"[{self.ip} {self.sku}] {text}", flush=True)

    def reply(self, host, cmd, data):
        msg = json.dumps({"msg": {"cmd": cmd, "data": data}}).encode()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as out:
            out.bind((self.ip, 0))  # so the app can tell the lights apart
            out.sendto(msg, (host, 4002))

    def scan_reply(self, host):
        self.reply(host, "scan", {"ip": self.ip, "device": self.device, "sku": self.sku,
                                  "bleVersionHard": "3.01.01", "bleVersionSoft": "1.04.04",
                                  "wifiVersionHard": "1.00.10", "wifiVersionSoft": "1.02.11"})

    def serve(self):
        while True:
            payload, (host, _port) = self.ctrl.recvfrom(4096)
            try:
                msg = json.loads(payload)["msg"]
            except (ValueError, KeyError):
                continue
            cmd, data = msg["cmd"], msg.get("data", {})
            if cmd == "devStatus":
                self.reply(host, "devStatus", self.state)
            elif cmd == "turn":
                self.state["onOff"] = data["value"]
                self.log(f"power {'on' if data['value'] else 'off'}")
            elif cmd == "brightness":
                self.state["brightness"] = data["value"]
                self.log(f"brightness {data['value']}")
            elif cmd == "colorwc":
                self.state["color"] = data["color"]
                self.state["colorTemInKelvin"] = data.get("colorTemInKelvin", 0)
                self.log(f"colour {data}")
            elif cmd == "razer":
                frame = base64.b64decode(data["pt"])
                if frame[3] == 0xB1:
                    self.log(f"streaming {'on' if frame[4] else 'off'}")
                else:
                    n = frame[5]
                    colors = [tuple(frame[6 + i * 3:9 + i * 3]) for i in range(n)]
                    self.log("frame " + " ".join("#%02x%02x%02x" % c for c in colors))
            elif cmd == "scan":
                self.scan_reply(host)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    lights = [FakeLight(i, f"127.0.0.{i + 1}", args.quiet) for i in range(args.count)]
    for light in lights:
        threading.Thread(target=light.serve, daemon=True).start()

    scan = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    scan.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    scan.bind(("", 4001))
    mreq = struct.pack("4s4s", socket.inet_aton(GROUP), socket.inet_aton("0.0.0.0"))
    scan.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    print(f"{len(lights)} fake light(s) ready", flush=True)
    while True:
        payload, (host, _port) = scan.recvfrom(4096)
        if b'"scan"' in payload:
            for light in lights:
                light.scan_reply(host)


if __name__ == "__main__":
    main()
