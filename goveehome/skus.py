"""What we know about individual Govee models.

Only the bits that matter for this app: a friendly product name, how many
segments the light has for light shows, whether it takes the LAN segment
streaming protocol (DreamView / Razer), which Bluetooth colour command it
understands and how it is usually mounted. Models that aren't listed get
safe defaults; everything can be changed per light in the app, and with a
cloud API key the segment count is taken from the account.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    name: str
    segments: int = 1
    streaming: bool = False      # supports the LAN "razer" segment protocol
    ble_color_mode: int = 0x0D   # 0x02 older strips, 0x0D newer models
    layout: str = "whole"        # default screen sync layout, see sync.zones


def _m(name, segments=1, streaming=False, layout="whole", ble=0x0D):
    return ModelInfo(name, segments, streaming, ble, layout)


MODELS: dict[str, ModelInfo] = {
    # TV and monitor backlights
    "H6199": _m("DreamView T1 TV Backlight", 15, True, "u_shape"),
    "H6198": _m("DreamView T1 Pro TV Backlight", 15, True, "u_shape"),
    "H6097": _m("DreamView T2 TV Backlight", 15, True, "u_shape"),
    "H6168": _m("Envisual TV Backlight T2", 15, True, "u_shape"),
    "H604A": _m("DreamView G1 Monitor Backlight", 15, True, "u_shape"),
    "H604B": _m("DreamView G1 Pro Monitor Backlight", 15, True, "u_shape"),
    "H604C": _m("DreamView G1S Monitor Backlight", 15, True, "u_shape"),
    "H66A0": _m("TV Backlight 3 Lite", 15, True, "u_shape"),
    "H66A1": _m("TV Backlight 3", 15, True, "u_shape"),
    # Light bar pairs: one light, two bars
    "H6046": _m("RGBIC TV Light Bars", 10, True, "bars"),
    "H6047": _m("RGBIC Gaming Light Bars", 10, True, "bars"),
    "H6056": _m("Flow Plus Light Bars", 12, True, "bars"),
    "H6057": _m("Flow Pro Light Bars", 12, True, "bars"),
    "H6059": _m("RGBWW Night Light Bars", 1, False, "whole"),
    # Gaming / desk strips
    "H6609": _m("Gaming Light Strip G1", 15, True, "top"),
    "H6608": _m("Gaming Light Strip", 15, True, "top"),
    "H61E1": _m("LED Strip M1", 15, True, "columns"),
    "H61E0": _m("LED Strip M1", 15, True, "columns"),
    # RGBIC strips
    "H6117": _m("Dream Color LED Strip", 15, False, ble=0x02),
    "H618A": _m("RGBIC Basic LED Strip", 10, True),
    "H618C": _m("RGBIC Basic LED Strip", 10, True),
    "H618E": _m("RGBIC LED Strip", 10, True),
    "H618F": _m("RGBIC LED Strip", 10, True),
    "H619A": _m("RGBIC Strip with Protective Coating", 10, True),
    "H619B": _m("RGBIC Strip", 10, True),
    "H619C": _m("RGBIC Strip", 10, True),
    "H619D": _m("RGBIC Strip", 10, True),
    "H619E": _m("RGBIC Strip", 10, True),
    "H619Z": _m("RGBIC Strip", 10, True),
    "H61A0": _m("RGBIC Neon Strip", 10, True),
    "H61A1": _m("RGBIC Neon Strip", 10, True),
    "H61A2": _m("RGBIC Neon Strip", 10, True),
    "H61A3": _m("RGBIC Neon Strip", 10, True),
    "H61A5": _m("Neon Strip", 10, True),
    "H61A8": _m("Neon Rope Light", 10, True),
    "H61B2": _m("RGBIC Neon TV Backlight", 10, True, "u_shape"),
    "H61BA": _m("RGBIC LED Strip 2", 10, True),
    "H61BC": _m("RGBIC LED Strip 2", 10, True),
    "H61BE": _m("RGBIC LED Strip 2", 10, True),
    "H61C3": _m("RGBIC Neon Strip 2", 10, True),
    "H61C5": _m("RGBIC Neon Strip 2", 10, True),
    "H61D3": _m("Neon Rope Light 2", 10, True),
    "H61D5": _m("Neon Rope Light 2", 10, True),
    "H6172": _m("Outdoor RGBIC Strip", 10, False),
    "H6173": _m("Outdoor RGBIC Strip", 10, False),
    "H6175": _m("Outdoor RGBIC Strip", 10, False),
    "H6176": _m("Outdoor RGBIC Strip", 10, False),
    # Plain RGB strips
    "H6110": _m("LED Strip", ble=0x02),
    "H6141": _m("LED Strip", ble=0x02),
    "H6143": _m("LED Strip", ble=0x02),
    "H6144": _m("LED Strip", ble=0x02),
    "H6159": _m("RGB LED Strip", ble=0x02),
    "H6160": _m("RGB LED Strip", ble=0x02),
    "H6163": _m("RGB LED Strip", ble=0x02),
    # Lamps
    "H6072": _m("RGBICWW Corner Floor Lamp", 7, True),
    "H6076": _m("RGBICW Floor Lamp Basic", 7, True),
    "H6078": _m("RGBICW Floor Lamp Pro", 7, True),
    "H607C": _m("Floor Lamp 2", 7, True),
    "H6052": _m("Aura Table Lamp"),
    "H6051": _m("Aura Table Lamp"),
    "H6020": _m("Table Lamp"),
    "H6022": _m("Table Lamp 2"),
    "H6038": _m("Wall Sconces"),
    "H6039": _m("Wall Sconces"),
    # Panels and wall lights
    "H6061": _m("Glide Hexa Light Panels", 10, True),
    "H6062": _m("Glide Wall Light", 6, True),
    "H6063": _m("Glide Wall Light", 6, True),
    "H6065": _m("Glide Y Lights", 10, True),
    "H6066": _m("Glide Hexa Pro", 10, True),
    "H6067": _m("Glide Triangle Light Panels", 10, True),
    "H6069": _m("Glide Lively Hexa", 10, True),
    "H610A": _m("Glide Lively Wall Lights", 6, True),
    "H610B": _m("Music Wall Lights", 6, True),
    # Bulbs, downlights
    "H6006": _m("Smart LED Bulb"),
    "H6008": _m("Smart LED Bulb"),
    "H6009": _m("Smart LED Bulb"),
    "H600D": _m("Smart LED Bulb"),
    "H6010": _m("Smart LED Bulb"),
    "H601A": _m("Recessed Downlight"),
    "H601B": _m("Recessed Downlight"),
    "H601C": _m("Recessed Downlight"),
    "H601D": _m("Recessed Downlight"),
    "H6087": _m("Smart Wall Light"),
    "H6088": _m("Cube Wall Light"),
    "H608A": _m("Ceiling Light"),
    "H608B": _m("Ceiling Light"),
    "H60A0": _m("Ceiling Light"),
    # Outdoor
    "H7020": _m("Outdoor String Lights", 10, False),
    "H7021": _m("Outdoor String Lights", 10, False),
    "H7028": _m("Outdoor Lynx Dream Lights", 10, False),
    "H7041": _m("Outdoor Lights", 10, False),
    "H7042": _m("Outdoor Lights", 10, False),
    "H7050": _m("Outdoor Pathway Lights", 1, False),
    "H7051": _m("Outdoor Pathway Lights", 1, False),
    "H7055": _m("Outdoor Pathway Lights", 1, False),
    "H705A": _m("Outdoor Permanent Lights", 10, False),
    "H705B": _m("Outdoor Permanent Lights", 10, False),
    "H705C": _m("Outdoor Permanent Lights", 10, False),
    "H7060": _m("Outdoor Flood Lights", 1, False),
    "H7061": _m("Outdoor Flood Lights", 1, False),
    "H7062": _m("Outdoor Flood Lights", 1, False),
    "H70B1": _m("Curtain Lights", 10, True),
    "H70C1": _m("Christmas String Lights", 10, False),
    "H70C2": _m("Christmas String Lights", 10, False),
}

# Some lights report more segments to the cloud than they physically have.
# The H6056 reports 15, but only 12 light up (6 per bar).
PHYSICAL_SEGMENTS: dict[str, int] = {"H6056": 12}


def lookup(sku: str) -> ModelInfo:
    sku = (sku or "").upper()
    info = MODELS.get(sku)
    if info is not None:
        return info
    return ModelInfo(f"Govee {sku}" if sku else "Govee light", 1, False, 0x0D, "whole")


def segment_count(sku: str, cloud_count: int = 0) -> int:
    """Best guess of the real number of segments."""
    sku = (sku or "").upper()
    count = cloud_count or lookup(sku).segments
    if sku in PHYSICAL_SEGMENTS:
        count = min(count, PHYSICAL_SEGMENTS[sku])
    return max(1, count)
