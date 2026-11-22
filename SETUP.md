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
sudo dnf install ~/rpmbuild/RPMS/noarch/goveehome-1.8.5-1.*.noarch.rpm
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

### Choose the style

Screen sync → **Style**:

- **Parts of the screen** (the default): the screen is split into 50 parts (10×5) and
  each part's colour is tracked. Switch *Detailed (50 parts)* off for 9 bigger parts (3×3),
  like version 1.8.4. Every segment of a light shows the colour of the
  part it sits next to, so set the *Mounting* on the light's page (next section); a strip
  left on *Whole screen* runs around the screen, up the left, across the top, down the
  right and along the bottom. Lights that only show one colour get the colour and the
  brightness of the screen. The options below (colour strength, intensity, smoothing,
  panel) apply here too.
- **Whole light, like GoveeScreen**: each light shows the colour of the
  screen and its brightness follows how bright the screen is, exactly like GoveeScreen on
  Windows. Works with every light that has LAN control and needs no setup. Options:
  *Colour* (dominant or average), *Colour strength* (how clearly the screen's colour is
  shown; a plain screen average is a pale mix that lights show as almost white, so keep it
  at *Strong* unless you want exactly GoveeScreen's output), *Intensity* (50 %, 100 %,
  200 %, max), *Smooth transitions*, *Leave out the panel / taskbar*.
- **Zones per segment**: segment lights get a colour per part of the screen, depending on
  how they're mounted (next section). The settings for it (colour pick, vividness, smoothing,
  edge depth) only show when this style is selected.

If you're not sure, keep *Parts of the screen*. You can switch while screen sync runs. If segment lights
show one colour only, run the *colour test* on the light's page: it finds out whether the
light takes a colour per segment.

### Tell the app how each light is mounted

Open a light and scroll to **Light shows**:

- **Use for screen sync / music / effects**: whether this light joins in. You can also pick
  the lights right on each light show's page (see below).
- **Segment streaming**: sends one colour per segment. Turned on automatically for models
  known to support it (DreamView TV backlights, light bars, RGBIC strips, Glide panels and
  others). If your light has DreamView in the Govee app, it very likely works; just try it.
  When it's off, the light gets one colour for its zone.
- **Segments**: how many separately coloured pieces the light has. The default comes from
  the model (or your Govee account if you added an API key).
- **Mounting**: where the light gets its colours from:
  - *Whole screen*: bulbs and lamps around the room
  - *Left, top, right (TV backlight)*: a strip running up the left side of the TV or
    monitor, across the top and down the right side
  - *All four edges*: the same, plus the bottom
  - *Top edge*, *Bottom edge*, *Left edge*, *Right edge*: a strip along one side
  - *Columns*: panels or a strip spread across the wall behind the screen
  - *Two bars, left and right of the screen*: light bar pairs like the H6046, H6047 and
    H6056 standing next to the monitor. *Right and left* is the same with the bars the other
    way round, *above and below* for bars lying flat
- **Reverse direction**: the light runs the other way. For light bars, each bar is flipped
  upside down and stays on its side.
- **Check the mounting → Identify**: shows test colours for a few seconds. If everything is
  set up right, the light is **red on the left** side of the screen and **blue on the
  right**, both bright at the top and dim at the bottom, **green** along the top and
  **yellow** along the bottom. If the colours are on the wrong side, try the other bar order
  or *Reverse direction* and press *Identify* again.

**H6056 Flow Plus light bars:** the app sets them up as 12 segments (6 per bar, the cloud
says 15 but only 12 exist) with *Two bars, left and right*. Stand the bars next to the
monitor, press *Identify*, and if red shows on the right bar choose *Two bars, right and
left*. If bright and dim are upside down, turn on *Reverse direction*.

### Choosing the lights

Every light show page (Screen sync, Music, Effects) has a **Lights** list right below the
preview. Switch each light on or off there, or use **All**, **None** or **Group** (takes the
lights of one of your groups). Changes apply while the show runs.

### Start it

Go to **Screen sync** in the sidebar and press **Start** (or press Ctrl+1).

On Wayland (GNOME, KDE Plasma) your desktop asks which screen to share. Pick the monitor the
lights are behind. On GNOME you'll see the screen sharing indicator in the top bar while sync
runs; that's expected. The choice is remembered, so the dialog doesn't come back next time
(*Capture → Shared screen → Ask again* resets it).

On X11 there's no dialog. With more than one monitor, pick the right one under
*Capture → Monitor*.

The status line under the preview shows how many updates per second go out and how long a
frame takes from capture to the light command.

The preview shows what the app sees with each light's zones drawn on top. Check that the
colours on the light match the zones. Changes to mounting, direction and all the sliders
apply while it runs.

**Follow the video** (on by default): when a film or game plays in a window, the screen edges
are usually a white web page or the desktop, and lights that look at the edges would just
turn white. The app notices where the picture moves and lays the zones over the video
instead; you can see the zones move onto it in the preview. When nothing moves for about ten
seconds, or the video goes fullscreen, it uses the whole screen again.

### Getting the colours to match

The defaults are a good start. If the lights still don't look like the screen, in this order:

1. **Colour correction** (on each light's page): most LED strips look bluish or greenish next
   to a monitor. Press *Show*, so the light shows white, and lower the channel that's too
   strong until the white matches your screen's white.
2. **LED gamma** (Screen sync → Colours): LEDs at half power look much brighter than a screen
   at half brightness. Gamma makes up for that. Colours look washed out or pastel → raise it
   (2.2–2.6). Dark scenes are too dark on the lights → lower it (1.6–1.8).
3. **Colour pick**: *Colourful* (the default) takes the strongest colour in a zone and lets it
   win over white, grey and black areas, so a zone that is half white page and half red video
   gives red, and a zone full of different colours gives the strongest of them instead of a
   grey mix. *Dominant colour* takes the colour that covers the most of the zone. *Exact
   average* is the plain average of everything in the zone; it matches the screen literally,
   which mostly means grey and white.
4. **Vividness** (default 4) turns screen colours into clean light colours, like Saturation
   in Govee's own app. Keep it high for lights with white LEDs (RGBWW, e.g. the H6056); set
   it to 1 for colours exactly as on screen. **Saturation** 100–130 % and **Black level** (colours darker than this are sent as black,
   so dark scenes don't turn the lights a dim brown).
5. **Ignore black bars** stops letterboxed films from making the top and bottom zones black.
6. **Edge depth** (Capture): how far into the screen the edge zones reach. 25 % by default;
   higher picks up more of the picture, lower follows the very edge.

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
- *Mirrored spectrum*: bass in the middle, treble at both ends. Nice on light bars.
- *Energy*: colours drift with the music, brightness follows the volume.
- *Beat pulse*: a new colour flashes on every beat and fades out.
- *Bass glow*: the whole light glows with the bass.
- *Rolling*: colours run along the light, faster when it's loud.

**Colours**: pick one of 25 palettes (rainbow, warm, cool, neon, fire, ocean, forest,
sunset, aurora, pastel, candy, cyberpunk, vaporwave, lava, ice, gold, love, purple rain,
tropical, retro, club, Christmas, Halloween, white) or **Your colours**: up to six colours
you choose under *Your colours* with the + and − buttons. Changing one of them switches to
your palette. **Feel**: *Flowing* lets colours glide with the music, *Jumpy* flashes and
jumps to a new colour on every beat. **Sensitivity** decides what the lights react to: low
means only strong peaks and clear beats, high means quiet details move the lights too and
beats are picked up more easily. *Brightness* is a separate slider.

**Effects** (sidebar, Ctrl+3) are 117 effects rendered on the PC, in seven groups. Every
card plays a live preview of its effect while the page is open.

- *Slow and smooth*: nothing jumps, colours change gradually and moving lights glide from
  LED to LED: slow rainbow, colour drift, travelling light (one light travelling around the
  strip), two travellers, colour journey, slow comet, Christmas (red, green and warm white
  slowly travelling around the strip), lightning storm (shifting blues, strikes at
  irregular moments, never the same gap twice in a row), ember glow, calm ocean, starlight,
  pastel drift, sunset drift, soft breathing colours, slow northern lights

- *Animated*: moving, multi-coloured animations: juggle, sweep, beat bands, confetti,
  bouncing balls, ripple, rainbow chase, colour blocks, RGB spin, candy stripes, neon chase,
  ping pong, colour waves, kaleidoscope, galaxy, rainbow sparkle, double helix, spectrum
  sweep, comets (rainbow, ice, pink, fire, green), colour flows (cotton candy, tropical,
  inferno, mint and lime, cyber, deep sea), breathing colours, meteor shower, colour rain,
  pacifica, rainbow bounce, breathing rainbow, hyperspace, plasma ball, electric, stained
  glass, disco ball, heat wave, fireflies
- *Moods*: slowly flowing colour worlds: peacock, unicorn, watermelon, cherry blossom,
  lagoon, toxic, synthwave, rose gold, autumn, northern lights, morning glow, twilight,
  jungle, glacier, berry, citrus
- *Colourful*: rainbow, colour cycle, rainbow pulse, plasma, pastel dream
- *Your colours*: solid, gradient, three colours, breathe, colour fade, wave, chase, colour
  wipe, meteor, scanner, heartbeat, strobe
- *Nature*: candle, fire, lava lamp, aurora, ocean, underwater, sunset, sunrise alarm (slowly
  goes from dark to warm daylight over 10 minutes at speed 1), forest, starry night,
  thunderstorm, snowfall, digital rain
- *Party and seasons*: party, disco, twinkle, fireworks, police, Christmas, Halloween,
  Valentine, Easter, St Patrick's, New Year, red white and blue, festival of lights, winter
  wonderland

Click one to start it. **Options** apply live: speed, brightness, size (for moving things
like meteor, scanner and waves), reverse direction, and up to three colours for the effects
that use your colours.

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
- X11: install the GStreamer good plugins: `sudo dnf install gstreamer1-plugins-good`
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

**Screen sync: colours are mirrored or on the wrong side**

Press *Identify* on the light's page and follow what it shows (red = left, blue = right,
green = top, yellow = bottom). Change *Mounting* or *Reverse direction* until it matches.

**Screen sync: colours don't match the screen**

Go through [Getting the colours to match](#getting-the-colours-to-match). With more than one
monitor make sure the right one is captured (Wayland: *Ask again* and pick it; X11:
*Capture → Monitor*).

**Screen sync: the colours don't match the screen, or the light is white most of the time**

Make sure *Style* is **Whole light, like GoveeScreen** (the default since 1.8.2), *Colour* is
*Dominant colour* and *Colour strength* is *Strong* or *Full* (the defaults since 1.8.3). A
plain average of a screen is a pale mix of everything on it; lights show that as white.

**Screen sync: the lights show different colours than the screen (e.g. blue instead of red)**

Run **Check capture colours** (Screen sync → Capture → *Check*), or in a terminal:

```bash
goveehome-cli diagnose
```

Your screen turns red, green and blue for a few seconds while GoveeHome captures it. Some
desktops, KDE Plasma in particular, hand out the picture with colour channels in the wrong
order (red and blue swapped). The check sees that and corrects it from then on; the row
then says what was fixed. If it says the result wasn't clear, the colours were shown on a
different screen than the one you share for screen sync: move the GoveeHome window to the
shared screen and run it again.

**Screen sync: a light shows white or grey, but effects / plain colours look right**

Run the **colour test**: on the light's page, *Light shows → Colour test → Test colours*,
or in a terminal:

```bash
goveehome-cli test-light all
```

It shows red twice, once with segment streaming and once as a plain colour, and asks what
the light shows. Many RGBIC strips (for example the H61A0 neon strip) accept segment
streaming frames but display them wrong, as white or grey. If only the plain colour shows
red, the test switches segment streaming off for that light, and screen sync sends it one
strong colour instead. If streaming works, it stays on. `goveehome-cli diagnose` runs the
same test at the end.

Since 1.8.0, segment streaming is only switched on by default for lights where it is known
to work (DreamView backlights, light bars, gaming strips); the test turns it on for others.

**Screen sync: the lights are white or grey (H6056 and other RGBWW lights)**

Lights with extra white LEDs (RGBWW / RGBICWW, among them the H6056 Flow Plus bars) turn
the part of a colour that all three channels share into white light. Screen colours almost
always have such a part, so before 1.7.0 these lights looked white or grey during screen
sync, while effects and music (pure colours) looked fine. Update to 1.7.0 or newer and keep
**Vividness** (Screen sync → Colours) at 4 or higher; raise it if colours still look pale.
That's the same thing the *Saturation* slider in Govee's own PC app does.

**Screen sync on KDE Plasma: lights are white or grey**

- **HDR:** if HDR is switched on for your screen (System Settings → Display & Monitor, the
  *HDR* option of your screen), KDE's screen capture comes out washed out and dim. Version 1.6.0 and
  newer detect that and bring the colour back with *Colour boost* (Screen sync → Colours,
  on by default); the details line under the preview says "KDE HDR is on" and shows the
  boost. If it still looks pale, raise *Saturation*, or switch HDR off while you use screen
  sync.
- **The share dialog:** when KDE asks what to share, pick the screen itself (not
  "Full workspace" with several screens, and not a window or region).
- **Report:** press *Copy report* on the Screen sync page while it runs and paste it into a
  GitHub issue, or run `goveehome-cli diagnose` with something colourful on the screen. It
  shows what KDE delivers (format, how colourful the picture is) and what each light gets.

**Screen sync: the lights only change brightness, not colour**

Update to 1.5.0 or newer. Older versions averaged each zone (and, for lights without segment
streaming, the whole screen) into one colour, and different colours average out to grey or
white. Now the strongest colour wins. Check that *Colour pick* is *Colourful* and
*Follow the video* is on.

Then look at the Screen sync page while it runs:

- The line under the status says how much of the captured picture is colourful. If it says
  0 % while your screen is clearly colourful, capture is the problem: press *Copy report*
  and open an issue on GitHub with it.
- Each light in the list has a colour strip showing exactly what it is being sent. If the
  strip is colourful but the light stays white, press *Identify* on the light's page. If the
  light shows red and blue there, raise *Saturation*. If it doesn't, the light doesn't take
  segment streaming: turn *Segment streaming* off for it; it then gets one strong colour.

**Lights flash or flicker at random**

- Update to 1.3.0 or newer. Older versions re-sent the "streaming on" command every 10
  seconds, which makes some lights blink, and passed on the odd empty frame from screen
  capture.
- If a dark film flickers at the top and bottom, turn off *Ignore black bars*.
- Raise *Smoothing* a little (60–100 ms) if the picture itself is very busy.

**Colours lag behind**

- Update to 1.3.0 or newer: capture can't build up a queue of old frames any more, and on X11
  it uses shared memory, which is several times faster on big screens.
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

### From inside the app (1.2.0 and newer)

GoveeHome looks for a new version on GitHub once a day. When there is one, **Update
available** shows up at the top of the sidebar. You can also check yourself: menu → **Check
for Updates…**, or *Preferences → Updates → Check now*.

The update window lists what changed. **Update** downloads the newest version from GitHub
and installs it over the current one, then **Restart now** opens the new version; a light
show that was running starts again by itself. Your settings are kept. Nothing needs root,
so there's no password prompt.

If an update needs new system packages, the update window says what failed. Run the manual
update below once, which installs them.

From a terminal the same works with:

```bash
goveehome-cli update
```

`goveehome-cli update --check` only shows whether there's something new.

If you run GoveeHome straight from a git clone (`python3 -m goveehome`), the updater does a
`git pull` instead. An RPM install is updated with `dnf`, not from inside the app.

### By hand

In the folder you cloned:

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

### Clean reinstall

Removes the installed app first, keeps your settings and lights, then installs the newest
version from scratch:

```bash
cd GoveeHome-For-Linux
```

```bash
./uninstall.sh
```

```bash
git pull
```

```bash
./install.sh
```

Don't have the cloned folder any more? Clone it fresh and install from there:

```bash
git clone https://github.com/Vanquish1905/GoveeHome-For-Linux.git
```

```bash
cd GoveeHome-For-Linux
```

```bash
./uninstall.sh
```

```bash
./install.sh
```

## 13. Uninstall

```bash
./uninstall.sh
```

This removes the app, the launchers and the service but keeps your settings. To remove those
too:

```bash
./uninstall.sh --purge
```
