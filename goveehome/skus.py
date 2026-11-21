"""What we know about individual Govee models.

Only the bits that matter for this app: a friendly product name, how many
addressable segments the light exposes over the LAN streaming protocol, and
which Bluetooth colour command it understands. Anything not listed falls back
to safe defaults and can be changed per device in the app.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    name: str
    segments: int = 1
    streaming: bool = False      # supports the LAN "razer" segment protocol
    ble_color_mode: int = 0x02   # 0x02 older strips, 0x0D newer models
    layout: str = "whole"        # default screen sync layout, see sync.zones


MODELS: dict[str, ModelInfo] = {
    # TV and monitor backlights
    "H6199": ModelInfo("DreamView T1 TV Backlight", 10, True, 0x0D, "u_shape"),
    "H6198": ModelInfo("DreamView T1 Pro TV Backlight", 10, True, 0x0D, "u_shape"),
    "H6046": ModelInfo("RGBIC TV Light Bars", 10, True, 0x0D, "columns"),
    "H6047": ModelInfo("RGBIC Gaming Light Bars", 10, True, 0x0D, "columns"),
    "H6056": ModelInfo("Flow Plus Light Bars", 6, True, 0x0D, "columns"),
    "H6168": ModelInfo("Envisual TV Backlight T2", 15, True, 0x0D, "u_shape"),
    "H604A": ModelInfo("DreamView G1 Monitor Backlight", 15, True, 0x0D, "u_shape"),
    "H604B": ModelInfo("DreamView G1 Pro Monitor Backlight", 15, True, 0x0D, "u_shape"),
    "H6609": ModelInfo("Gaming Light Strip G1", 15, True, 0x0D, "columns"),
    "H66A0": ModelInfo("TV Backlight 3 Lite", 15, True, 0x0D, "u_shape"),
    # Strips
    "H6143": ModelInfo("LED Strip Light", 1, False, 0x02),
    "H6160": ModelInfo("RGB LED Strip", 1, False, 0x02),
    "H6163": ModelInfo("RGB LED Strip", 1, False, 0x02),
    "H6117": ModelInfo("Dream Color LED Strip", 15, False, 0x02),
    "H619A": ModelInfo("RGBIC Strip with Protective Coating", 10, True, 0x0D),
    "H619C": ModelInfo("RGBIC Strip", 10, True, 0x0D),
    "H619E": ModelInfo("RGBIC Strip", 10, True, 0x0D),
    "H61A0": ModelInfo("RGBIC Neon Strip", 10, True, 0x0D),
    "H61A2": ModelInfo("RGBIC Neon Strip", 10, True, 0x0D),
    "H61E1": ModelInfo("LED Strip M1", 15, True, 0x0D, "columns"),
    "H6172": ModelInfo("Outdoor RGBIC Strip", 10, False, 0x0D),
    # Lamps and panels
    "H6076": ModelInfo("RGBICW Floor Lamp Basic", 7, True, 0x0D),
    "H6072": ModelInfo("RGBICWW Corner Floor Lamp", 7, True, 0x0D),
    "H6062": ModelInfo("Glide Wall Light", 6, True, 0x0D),
    "H6061": ModelInfo("Glide Hexa Light Panels", 10, True, 0x0D),
    "H6065": ModelInfo("Glide Y Lights", 10, True, 0x0D),
    "H6066": ModelInfo("Glide Hexa Pro", 10, True, 0x0D),
    "H6067": ModelInfo("Glide Triangle Light Panels", 10, True, 0x0D),
    "H610A": ModelInfo("Glide Lively Wall Lights", 6, True, 0x0D),
    "H610B": ModelInfo("Music Wall Lights", 6, True, 0x0D),
    "H6052": ModelInfo("Aura Table Lamp", 1, False, 0x0D),
    "H6022": ModelInfo("Table Lamp 2", 1, False, 0x0D),
    "H6008": ModelInfo("Smart LED Bulb", 1, False, 0x0D),
    "H6009": ModelInfo("Smart LED Bulb", 1, False, 0x0D),
    "H600D": ModelInfo("Smart LED Bulb", 1, False, 0x0D),
    "H6159": ModelInfo("RGB Light Strip", 1, False, 0x02),
    "H70B1": ModelInfo("Curtain Lights", 10, True, 0x0D),
}

DEFAULT = ModelInfo("Govee light", 1, False, 0x02)


def lookup(sku: str) -> ModelInfo:
    return MODELS.get((sku or "").upper(), DEFAULT)
