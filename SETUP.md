# Setup guide

This walks through everything from a fresh install to lights following your screen and
music. Fedora is covered first, other distributions follow further down.

1. [Prepare the lights](#1-prepare-the-lights)
2. [Install on Fedora](#2-install-on-fedora)
3. [Install on other distributions](#3-install-on-other-distributions)
4. [First start](#4-first-start)
5. [Set up screen sync](#5-set-up-screen-sync)
6. [Music and effects](#6-music-and-effects)
7. [Groups, timers and saved colours](#7-groups-timers-and-saved-colours)
8. [Running in the background](#8-running-in-the-background)
9. [Optional: cloud API key](#9-optional-cloud-api-key)
10. [Optional: Bluetooth](#10-optional-bluetooth)
11. [Troubleshooting](#11-troubleshooting)
12. [Updating](#12-updating)
13. [Uninstall](#13-uninstall)

---

## 1. Prepare the lights

The app talks to the lights over your local network using Govee's LAN API. It is off by
default, so for **every light**:

1. Open the Govee Home app on your phone.
2. Tap the light, then the gear icon in the top right.
3. Turn on **LAN Control**. If you don't see the switch, update the light's firmware from
   the same screen first. A few older or very cheap models don't have it at all; those can
   still be used through the cloud key (section 9) or Bluetooth (section 10).

Your PC and the lights need to be on the same network. Most guest networks and some mesh
systems keep devices apart ("client isolation" / "AP isolation"); if that's on, the PC can't
see the lights.

## 2. Install on Fedora

Fedora 39 or newer, Workstation (GNOME) or the KDE Plasma edition.

```bash
sudo dnf install git
```

```bash
git clone https://github.com/Vanquish1905/GoveeHome-For-Linux.git
```

```bash
cd GoveeHome-For-Linux
```

```bash
./install.sh
```

The script:

- installs the system packages it needs with `dnf` (asks for your password):
  `python3-gobject python3-cairo python3-numpy python3-pillow gtk4 libadwaita gstreamer1-plugins-base gstreamer1-plugins-good pipewire-gstreamer`
- creates a private Python environment in `~/.local/share/goveehome/venv`
- puts `goveehome` and `goveehome-cli` in `~/.local/bin`
- adds GoveeHome to your app menu
- checks the firewall (see below)

Nothing is installed system wide apart from the distribution packages.

### Firewall

Lights answer on **UDP port 4002**. Fedora Workstation's default firewall zone already
allows it. Other editions, Server and custom setups may not, and then no lights show up. The installer checks and offers to open the port. To do it by hand:

```bash
sudo firewall-cmd --permanent --add-port=4002/udp
```

```bash
sudo firewall-cmd --reload
```

### Building an RPM instead

If you'd rather have a proper package:

```bash
sudo dnf install rpm-build python3-devel pyproject-rpm-macros desktop-file-utils libappstream-glib
```

```bash
make rpm
```

```bash
sudo dnf install ~/rpmbuild/RPMS/noarch/goveehome-1.1.0-1.*.noarch.rpm
```

## 3. Install on other distributions

`./install.sh` also knows `apt` (Ubuntu, Debian, Mint, Pop!_OS), `pacman` (Arch, EndeavourOS,
Manjaro) and `zypper` (openSUSE). You need libadwaita 1.4 or newer, which means Ubuntu 24.04,
Debian 13, or anything current on a rolling release.

If your distribution isn't covered, install these yourself and run `./install.sh --no-deps`:

| What | Typical package names |
| --- | --- |
| PyGObject + cairo bindings | `python3-gobject`, `python3-gi`, `python3-gi-cairo`, `python-gobject` |
| GTK 4 and libadwaita | `gtk4`, `libadwaita`, `gir1.2-gtk-4.0`, `gir1.2-adw-1` |
| numpy and Pillow | `python3-numpy` `python3-pillow`, `python3-pil`, `python-pillow` |
| GStreamer + PipeWire plugin (Wayland capture) | `gstreamer1-plugins-base` + `pipewire-gstreamer`, `gstreamer1.0-pipewire`, `gst-plugin-pipewire` |
| GStreamer PulseAudio plugin (music sync) | `gstreamer1-plugins-good`, `gstreamer1.0-pulseaudio`, `gst-plugins-good` |

`ufw` users (Ubuntu) with the firewall on:

```bash
sudo ufw allow 4002/udp
```

## 4. First start

Open **GoveeHome** from the app menu, or run `goveehome`.

Lights with LAN Control turned on show up in the sidebar within a few seconds. Click one to
control it: the switch in the header turns it on and off, below that are brightness, white
temperature, colour presets and a colour picker.

No lights after ten seconds or so? Press the refresh button once more, then go through
[Troubleshooting](#11-troubleshooting).

Lights can also be added by IP address (menu → *Add Light by Address…*). You find the
address in your router's list of connected devices; the light is usually called something
like `ihoment_H6199_XXXX`.

## 5. Set up screen sync

### Tell the app how each light is mounted

Open a light and scroll to **Light shows**:

- **Use for screen sync / music / effects**: whether this light joins in.
- **Segment streaming**: sends one colour per segment. Turned on automatically for models
  known to support it (DreamView TV backlights, light bars, RGBIC strips, Glide panels and
  others). If your light has DreamView in the Govee app, it very likely works; just try it.
  When it's off, the light gets one colour for its zone.
- **Segments**: how many separately coloured pieces the light has. The default comes from
  the model. More isn't better if the light doesn't have them.
- **Mounting**: where the light gets its colour from:
  - *Whole screen*: bulbs and lamps around the room
  - *Left, top, right (TV backlight)*: a strip running up the left side of the TV or
    monitor, across the top and down the right side
  - *All four edges*: the same, plus the bottom
  - *Top edge*, *Bottom edge*, *Left edge*, *Right edge*: a strip along one side
  - *Columns*: light bars or panels standing next to the screen
- **Check the direction → Identify**: lights up red where the mounting starts (bottom left
  for a TV backlight) and blue where it ends, for a few seconds. If red and blue are on the
  wrong sides, turn on **Reverse direction**.

### Start it

Go to **Screen sync** in the sidebar and press **Start** (or press Ctrl+1).

On Wayland (GNOME, KDE Plasma) your desktop asks which screen to share. Pick the monitor the
lights are behind. On GNOME you'll see the screen sharing indicator in the top bar while sync
runs; that's expected. The choice is remembered, so the dialog doesn't come back next time
(*Capture → Shared screen → Ask again* resets it).

On X11 there's no dialog. With more than one monitor, pick the right one under
*Capture → Monitor*.

The preview shows what the app sees with each light's zones drawn on top. Check that the
colours on the light match the zones. Changes to mounting, direction and all the sliders
apply while it runs.

### Getting the colours to match

The defaults are a good start. If the lights still don't look like the screen, in this order:

1. **Colour correction** (on each light's page): most LED strips look bluish or greenish next
   to a monitor. Press *Show*, so the light shows white, and lower the channel that's too
   strong until the white matches your screen's white.
2. **LED gamma** (Screen sync → Colours): LEDs at half power look much brighter than a screen
   at half brightness. Gamma makes up for that. Colours look washed out or pastel → raise it
   (2.2–2.6). Dark scenes are too dark on the lights → lower it (1.6–1.8).
3. **Colour pick**: *Accurate* is the true average of each zone. *Vivid* leans towards the
   strong colours in a zone, good for games and cartoons. *Dominant* takes the colour that
   covers the most of the zone, good for films with small bright highlights.
4. **Saturation** 100–130 % and **Black level** (colours darker than this are sent as black,
   so dark scenes don't turn the lights a dim brown).
5. **Ignore black bars** stops letterboxed films from making the top and bottom zones black.

### Response

- **Smoothing** is in milliseconds. 0 follows every frame, 40 ms (the default) takes the
  edge off flicker, 150 ms and up is calm and soft. Scene cuts always come through
  immediately.
- **Updates per second**: 30 is smooth for segment streaming. Lights without segment
  streaming are capped at 15 because they can't keep up.

## 6. Music and effects

**Music** (sidebar, Ctrl+2) makes the lights react to whatever the PC plays, from any app.
It listens to the output of your speakers or headphones directly, so there's no microphone
involved and room noise doesn't matter. Modes:

- *Spectrum*: bass at one end of the light, treble at the other. Best on segmented lights.
- *Energy*: colours drift with the music, brightness follows the volume.
- *Beat pulse*: a new colour flashes on every beat and fades out.
- *Rolling*: colours run along the light, faster when it's loud.

*Colours* picks the palette, *Sensitivity* how strongly it reacts.

**Effects** (sidebar, Ctrl+3) are animated scenes rendered on the PC: rainbow, colour cycle,
gradient and breathe in your own colours, candle, fire, aurora, ocean, sunset, forest,
starry night, party and police. Click one to start it; speed and brightness change live.

Only one light show runs at a time. Starting another one stops the current one; Ctrl+.
stops all of them.

## 7. Groups, timers and saved colours

- **Groups**: *New group…* in the sidebar (or Ctrl+G). A group has the same controls as a
  single light and sends them to every light in it. *All lights* is always there.
- **Timer**: every light and group has *Turn off after*, from 5 minutes to 4 hours. Timers
  run in the app, so it has to keep running (see the next section).
- **Saved colours**: pick a custom colour and press **+** next to it. Saved colours show up
  on every light and group. Right-click one to remove it.

## 8. Running in the background

In **Preferences**:

- **Keep light shows running when the window is closed**: closing the window while a light
  show runs leaves it running. Open GoveeHome again from the app menu to get the window back;
  the show stops when you stop it or quit (Ctrl+Q).
- **Start at login**: starts GoveeHome without a window when you log in. Together with
  **Continue the last light show on start**, the lights pick up where you left off.
- **Follow the computer**: turn the lights off when the PC goes to sleep or shuts down, and
  back on (including a running light show) when it wakes up.

Prefer a service without the app? `goveehome-cli` can run any light show on its own, and
there's a systemd user unit for screen sync:

1. Start screen sync once from the app, so the screen share choice is remembered.
2. Install the service:

```bash
mkdir -p ~/.config/systemd/user
```

```bash
cp packaging/systemd/goveehome-sync.service ~/.config/systemd/user/
```

```bash
systemctl --user daemon-reload
```

```bash
systemctl --user enable --now goveehome-sync.service
```

It uses the same settings as the app. Stop it with
`systemctl --user stop goveehome-sync.service`, look at its output with
`journalctl --user -u goveehome-sync.service`. To run music or an effect instead, change
`ExecStart` to e.g. `%h/.local/bin/goveehome-cli music` or
`%h/.local/bin/goveehome-cli effect aurora`.

You can also bind `goveehome-cli` commands to keyboard shortcuts in your desktop settings,
for example `goveehome-cli off all` or `goveehome-cli color "Desk lamp" warm`.

## 9. Optional: cloud API key

Without a key everything runs locally. A key adds:

- lights that don't support LAN Control (they get controlled through the cloud, with a short
  delay; they can't take part in light shows)
- the names you gave your lights in the phone app
- scenes, including the DIY scenes you made in the phone app; they run on the light itself,
  so they keep going when the PC is off
- **Segments**: give single segments of RGBIC lights their own colour
- **Music mode on the light**: the music modes that use the light's own microphone
- extra switches some lights have, like gradient or night light

To get one: Govee Home phone app → **Profile** (bottom right) → gear icon → **Apply for API
Key**. Fill in the form; the key arrives by e-mail, usually within minutes.

Paste it into GoveeHome → menu → **Preferences** → **API key** and press the check mark. The
app confirms how many devices it found on your account. The key is stored in
`~/.config/goveehome/config.json`, readable only by your user.

## 10. Optional: Bluetooth

For lights without Wi-Fi. The installer already includes the `bleak` library. Turn on
**Look for Bluetooth lights** in Preferences and press **Scan**. The light must be close to
the PC and must not be connected to your phone at the same time (close the Govee app).

Bluetooth is slow, so light shows over Bluetooth are limited to one colour, ten times a
second.

On Fedora, make sure Bluetooth is running:

```bash
sudo systemctl enable --now bluetooth
```

## 11. Troubleshooting

**No lights found**

- LAN Control must be on for each light (section 1). It sometimes turns itself off after a
  firmware update.
- Firewall: UDP port 4002 must be open (section 2). Quick test: temporarily
  `sudo systemctl stop firewalld`, refresh in the app. If lights appear, it's the firewall.
  Start it again afterwards: `sudo systemctl start firewalld`.
- PC and lights in the same network and subnet, no guest network, no AP isolation.
- Some routers drop multicast. Add the light's IP address in *Preferences → Local network*
  or via *Add Light by Address*. Giving the light a fixed IP in the router helps.
- Running a VPN? Many VPN clients route everything, including local traffic, through the
  tunnel. Allow LAN access in the VPN settings.
- Check from a terminal: `goveehome-cli -v list`

**"Cannot listen on UDP port 4002"**

Another program is already using the port, often Home Assistant's Govee integration or
govee2mqtt running on the same machine. Stop it, or run GoveeHome on a different PC.

**Screen sync: "No screen capture method available"**

- Wayland: install the PipeWire GStreamer plugin: `sudo dnf install pipewire-gstreamer`
- X11: install mss: `~/.local/share/goveehome/venv/bin/pip install mss`
- Sway, Hyprland and other wlroots compositors without a working screencast portal:
  `sudo dnf install grim` and pick *grim (wlroots)* as the source.

**Screen sync: the share dialog appears every time**

Your portal version doesn't support remembering the choice (needs xdg-desktop-portal 1.12+
with a desktop backend that supports it; current GNOME and KDE do). Updating the system
usually fixes it.

**Screen sync: the light only shows one colour**

Turn on *Segment streaming* for it and set the number of segments. If it still shows one
colour, the model doesn't support the streaming protocol; turn streaming off again so it
gets the plain colour command, which works on every light.

**Screen sync: colours are mirrored or rotated**

Flip *Reverse direction*, or pick a different mounting.

**Screen sync: colours don't match the screen**

Go through [Getting the colours to match](#getting-the-colours-to-match). With more than one
monitor make sure the right one is captured (Wayland: *Ask again* and pick it; X11:
*Capture → Monitor*).

**Colours lag behind**

- Lower *Smoothing*, down to 0 if you like.
- Use *Segment streaming* where the light supports it. Plain colour commands are capped at
  15 a second and some lights fade into each new colour, which looks slower.
- Check the Wi-Fi signal of the light; 2.4 GHz lights far away from the router drop packets.
- Bluetooth lights are slow by nature.

**Music: "needs the GStreamer PulseAudio plugin"**

```bash
sudo dnf install gstreamer1-plugins-good
```

**Music: the lights don't react**

Music sync listens to the default output device. If you switched outputs (e.g. to
headphones) while it was running, stop and start it again. Raise *Sensitivity* for quiet
music.

**The app doesn't start**

Run `goveehome` from a terminal to see the error. `GOVEEHOME_DEBUG=1 goveehome` prints more.
The most common cause is libadwaita older than 1.4.

## 12. Updating

```bash
cd GoveeHome-For-Linux
```

```bash
git pull
```

```bash
./install.sh
```

Your settings are kept. Settings from 1.0 that changed meaning (screen sync smoothing,
colour pick) are reset to the new defaults once.

## 13. Uninstall

```bash
./uninstall.sh
```

This removes the app, the launchers and the service but keeps your settings. To remove those
too:

```bash
./uninstall.sh --purge
```
