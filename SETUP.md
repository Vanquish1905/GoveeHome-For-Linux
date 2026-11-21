# Setup guide

This walks through everything from a fresh install to lights following your screen. Fedora
is covered first, other distributions follow further down.

1. [Prepare the lights](#1-prepare-the-lights)
2. [Install on Fedora](#2-install-on-fedora)
3. [Install on other distributions](#3-install-on-other-distributions)
4. [First start](#4-first-start)
5. [Set up screen sync](#5-set-up-screen-sync)
6. [Run sync in the background](#6-run-sync-in-the-background)
7. [Optional: cloud API key](#7-optional-cloud-api-key)
8. [Optional: Bluetooth](#8-optional-bluetooth)
9. [Troubleshooting](#9-troubleshooting)
10. [Uninstall](#10-uninstall)

---

## 1. Prepare the lights

The app talks to the lights over your local network using Govee's LAN API. It is off by
default, so for **every light**:

1. Open the Govee Home app on your phone.
2. Tap the light, then the gear icon in the top right.
3. Turn on **LAN Control**. If you don't see the switch, update the light's firmware from
   the same screen first. A few older or very cheap models don't have it at all; those can
   still be used through the cloud key (section 7) or Bluetooth (section 8).

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
  `python3-gobject python3-cairo python3-numpy gtk4 libadwaita gstreamer1-plugins-base pipewire-gstreamer`
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
sudo dnf install ~/rpmbuild/RPMS/noarch/goveehome-1.0.0-1.*.noarch.rpm
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
| numpy | `python3-numpy`, `python-numpy` |
| GStreamer + PipeWire plugin (Wayland capture) | `gstreamer1-plugins-base` + `pipewire-gstreamer`, `gstreamer1.0-pipewire`, `gst-plugin-pipewire` |

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
[Troubleshooting](#9-troubleshooting).

Lights can also be added by IP address (menu → *Add Light by Address…*). You find the
address in your router's list of connected devices; the light is usually called something
like `ihoment_H6199_XXXX`.

## 5. Set up screen sync

### Tell the app how each light is mounted

Open a light and scroll to **Screen sync**:

- **Use for screen sync**: whether this light joins in.
- **Segment streaming**: sends one colour per segment. Turned on automatically for models
  known to support it (DreamView TV backlights, light bars, RGBIC strips, Glide panels and
  others). If your light has DreamView in the Govee app, it very likely works; just try it.
  When it's off, the light gets one colour for the zone.
- **Segments**: how many separately coloured pieces the light has. The default comes from
  the model. More isn't better if the light doesn't have them.
- **Mounting**: where the light gets its colour from:
  - *Whole screen*: bulbs and lamps around the room
  - *Left, top, right (TV backlight)*: a strip running up the left side of the TV or
    monitor, across the top and down the right side
  - *All four edges*: the same, plus the bottom
  - *Top edge*, *Bottom edge*, *Left edge*, *Right edge*: a strip along one side
  - *Columns*: light bars or panels standing next to the screen
- **Reverse direction**: if the colours come out mirrored, the strip starts at the other end.
  Flip this.

### Start it

Go to **Screen sync** in the sidebar and press **Start**.

On Wayland (GNOME, KDE Plasma) your desktop asks which screen to share. Pick the monitor the
lights are behind. On GNOME you'll see the screen sharing indicator in the top bar while sync
runs; that's expected. The choice is remembered, so the dialog doesn't come back next time
(*Capture → Shared screen → Ask again* resets it).

On X11 there's no dialog; the app captures directly.

The preview shows what the app sees with each light's zones drawn on top. Check that the
colours on the light match the zones. If not, change mounting or reverse direction while it
runs; changes apply immediately.

### Tuning

- **Colour pick**: *Vivid* picks strong colours out of mostly grey images (a red logo on a
  grey page gives red, not pinkish grey). *Average* is the plain mean.
- **Saturation**: LEDs look washed out with pure screen colours, 120–150 % looks right for
  most people.
- **Brightness**: scales all colours.
- **Smoothing**: higher is calmer, lower reacts faster. Big jumps like scene cuts always come
  through quickly.
- **Black level**: colours darker than this are sent as black, which stops dark scenes from
  turning the lights into a dim brown.
- **Updates per second**: 20–30 is smooth for segment streaming. Plain colour lights are
  capped at 15 regardless because they can't keep up.
- **Edge depth**: how far into the screen the edge zones reach.

## 6. Run sync in the background

The app window has to stay open (minimised is fine) for sync to run. For an always-on setup
there's a user service that runs sync from the command line whenever you're logged in:

1. Start sync once from the app, so the screen share choice is remembered.
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
`journalctl --user -u goveehome-sync.service`.

You can also bind `goveehome-cli` commands to keyboard shortcuts in your desktop settings,
for example `goveehome-cli off all` or `goveehome-cli color "Desk lamp" warm`.

## 7. Optional: cloud API key

Without a key everything runs locally. A key adds:

- lights that don't support LAN Control (they get controlled through the cloud, with a short
  delay; they can't take part in screen sync)
- the names you gave your lights in the phone app
- scenes

To get one: Govee Home phone app → **Profile** (bottom right) → gear icon → **Apply for API
Key**. Fill in the form; the key arrives by e-mail, usually within minutes.

Paste it into GoveeHome → menu → **Preferences** → **API key** and press the check mark. The
app confirms how many devices it found on your account. The key is stored in
`~/.config/goveehome/config.json`, readable only by your user.

## 8. Optional: Bluetooth

For lights without Wi-Fi. The installer already includes the `bleak` library. Turn on
**Look for Bluetooth lights** in Preferences and press **Scan**. The light must be close to
the PC and must not be connected to your phone at the same time (close the Govee app).

Bluetooth is slow, so screen sync over Bluetooth is limited to one colour, ten times a
second.

On Fedora, make sure Bluetooth is running:

```bash
sudo systemctl enable --now bluetooth
```

## 9. Troubleshooting

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

**Colours lag behind**

Lower *Smoothing*. Check the Wi-Fi signal of the light; 2.4 GHz lights far away from the
router drop packets. Plain colour lights are capped at 15 updates a second by design.

**The app doesn't start**

Run `goveehome` from a terminal to see the error. `GOVEEHOME_DEBUG=1 goveehome` prints more.
The most common cause is libadwaita older than 1.4.

## 10. Uninstall

```bash
./uninstall.sh
```

This removes the app, the launchers and the service but keeps your settings. To remove those
too:

```bash
./uninstall.sh --purge
```
