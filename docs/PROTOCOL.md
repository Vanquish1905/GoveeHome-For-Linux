# Protocol notes

What the app sends to the lights, collected in one place. Byte values are hex.

## LAN API (UDP)

Lights with *LAN Control* enabled in the phone app speak JSON over UDP.

| Purpose | Destination | Notes |
| --- | --- | --- |
| Discovery | `239.255.255.250:4001` (multicast) | can also be sent unicast to a known IP |
| Replies | the sender's IP, port `4002` | so the client has to listen on 4002 |
| Commands | `<light ip>:4003` | no reply except for `devStatus` |

Every message looks like `{"msg": {"cmd": "<name>", "data": {...}}}`.

### Discovery

```json
{"msg":{"cmd":"scan","data":{"account_topic":"reserve"}}}
```

Reply:

```json
{"msg":{"cmd":"scan","data":{"ip":"192.168.1.23","device":"1F:80:C5:32:32:36:72:4E",
 "sku":"H6199","bleVersionHard":"3.01.01","bleVersionSoft":"1.03.01",
 "wifiVersionHard":"1.00.10","wifiVersionSoft":"1.02.03"}}}
```

`device` is the same id the cloud API uses, so lights found both ways can be merged.

### Commands

| Command | data |
| --- | --- |
| `turn` | `{"value": 1}` or `0` |
| `brightness` | `{"value": 1..100}` |
| `colorwc` | `{"color": {"r":255,"g":0,"b":0}, "colorTemInKelvin": 0}` |
| `colorwc` (white) | `{"color": {"r":0,"g":0,"b":0}, "colorTemInKelvin": 2000..9000}` |
| `devStatus` | `{}`, the light replies with `onOff`, `brightness`, `color`, `colorTemInKelvin` |

### Segment streaming (`razer`)

Lights that support DreamView / Razer Chroma take binary frames, base64 encoded:

```json
{"msg":{"cmd":"razer","data":{"pt":"<base64>"}}}
```

Switch streaming on and off:

```
BB 00 01 B1 01 0A      on   -> "uwABsQEK"
BB 00 01 B1 00 0B      off  -> "uwABsQAL"
```

Colour frame:

```
BB 00 LEN B0 GRAD N  R1 G1 B1  R2 G2 B2 ...  XOR
```

- `LEN` = `N * 3 + 2`
- `GRAD` = `01` to let the light blend between neighbouring colours, `00` for hard edges
- `N` = number of colours. The light spreads them over its physical segments.
- `XOR` = all previous bytes XORed together

While streaming is on, the light ignores its own effects. It drops out of streaming mode by
itself after a while without frames, so the app repeats the "on" frame every 10 seconds and
sends a frame at least once a second even when the picture doesn't change.

## Bluetooth LE

Write characteristic `00010203-0405-0607-0809-0a0b0c0d2b11`, 20 byte packets, last byte is
the XOR of the first 19, unused bytes are zero.

| Packet | Meaning |
| --- | --- |
| `33 01 01` / `33 01 00` | power on / off |
| `33 04 VV` | brightness, `VV` 00..FF |
| `33 05 02 RR GG BB` | colour (older strips) |
| `33 05 0D RR GG BB` | colour (most models since 2020) |
| `33 05 15 01 RR GG BB 00 00 00 00 00 FF 7F` | colour on all segments (some RGBIC strips) |
| `AA 01` | keep-alive, sent every 2 s while connected |

Lights advertise as `ihoment_<SKU>_XXXX`, `Govee_<SKU>_XXXX`, `GBK_...` or `Minger_...`.

## Cloud API

Base URL `https://openapi.api.govee.com/router/api/v1`, header `Govee-API-Key: <key>`.

| Call | Purpose |
| --- | --- |
| `GET /user/devices` | devices on the account with their capabilities |
| `POST /device/state` | current state |
| `POST /device/control` | change something |
| `POST /device/scenes` | available scenes |

Request bodies:

```json
{"requestId": "<uuid>", "payload": {"sku": "H6008", "device": "AA:BB:...",
  "capability": {"type": "devices.capabilities.on_off", "instance": "powerSwitch", "value": 1}}}
```

| What | type | instance | value |
| --- | --- | --- | --- |
| Power | `devices.capabilities.on_off` | `powerSwitch` | `0` / `1` |
| Brightness | `devices.capabilities.range` | `brightness` | `1..100` |
| Colour | `devices.capabilities.color_setting` | `colorRgb` | `(R << 16) + (G << 8) + B` |
| White | `devices.capabilities.color_setting` | `colorTemperatureK` | Kelvin |
| Scene | `devices.capabilities.dynamic_scene` | `lightScene` | option value from `/device/scenes` |

Limit: 10 000 requests per day per key.
