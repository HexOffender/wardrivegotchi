# Wardrivegotchi

This documentation uses ASD-STE100 Simplified Technical English.

## 1 Introduction

Wardrive operations need two functions. The equipment must find WiFi networks.
The equipment must also know its position.

The Hak5 WiFi Pineapple Pager has a WiFi radio. The Pager does not have a GPS
receiver.

This repository combines two projects into one payload. The wardrive dashboard
gets its position from the browser on your phone. You do not need a GPS
receiver. You do not need a USB dongle.

I am not the author of the two projects. The GPS server is a fork of
[mobile2gps](https://github.com/ryanpohlner/mobile2gps) by Ryan Pohlner. The
wardrive payload is a fork of
[pineapple_pager_wardrive](https://github.com/brainphreak/pineapple_pager_wardrive)
by brAinphreAk. Refer to [CREDITS.md](CREDITS.md) for the full attribution.

## 2 Why this repository is necessary

If you start the two payloads together, the GPS function does not operate. The
cause is not obvious in either project.

The Pager operates its own gpsd process. This gpsd process has no GPS device.
The Pager starts this process again each time its services start. The wardrive
payload stops and starts the Pager services. Thus the wardrive payload causes
the problem each time it starts.

The gpsd process of the Pager takes port 2947. It answers clients correctly. But
it has no device to read. Thus it never reports a position.

The failure is not easy to identify. The phone shows correct coordinates. The GPS
server writes correct data. The gpsd process operates. But the dashboard shows
`No Fix`.

There is a second problem. The wardrive payload starts gpsd again when you change
its GPS settings. It then connects gpsd to a serial device. But the phone GPS
server connects gpsd to a pseudo-terminal. The serial device `/dev/ttyACM0` does
not exist on this equipment. Thus the settings screen stops a correct GPS
function.

This repository corrects the two problems:

- The GPS server monitors its gpsd process. If a different gpsd process takes
  the port, the GPS server takes the port again.
- In phone mode, the payload does not stop or start gpsd. The GPS server has
  control of gpsd.

This repository also corrects other defects. Refer to [CREDITS.md](CREDITS.md)
for the list.

## 3 How the system operates

```
phone browser  --HTTPS-->  GPS server  --NMEA-->  pty  -->  gpsd  -->  wardrive
Geolocation API            (Go, GPL)         /dev/pts/N              dashboard
                                                                     Wigle CSV
```

The browser on the phone reports its position. The GPS server changes each
position into an NMEA `GPRMC` sentence. The GPS server then writes the sentence
to a pseudo-terminal. The gpsd process reads the pseudo-terminal as a usual
serial GPS receiver.

Thus all downstream software gets usual GPS data. This includes the wardrive
dashboard and the GPS screen of the Pager. You do not have to change this
software.

HTTPS is necessary. The browser Geolocation API does not operate in a page that
is not secure. Thus the page must use TLS, also on a local network.

The certificate is self-signed. Your browser shows a warning the first time. If
you accept the warning, the page is still a secure context. This is the condition
that the Geolocation API examines.

## 4 Installation

### 4.1 Install the payload

Do these steps on the Pager:

```sh
cd /root
git clone https://github.com/YOURNAME/wardrivegotchi.git
cd wardrivegotchi
./install.sh
```

The `install.sh` script copies the payload files. The script then gets the pager
control library and the fonts from the repository of brAinphreAk. This repository
does not contain those files. Refer to [CREDITS.md](CREDITS.md) for the reason.

The payload installs to its own directory,
`/root/payloads/user/reconnaissance/wardrivegotchi/`, and keeps everything it
needs inside it: the GPS server, the page, the library and the fonts. It does not
touch the `wardrive` or `mobile2gps` payloads, so you can keep those installed
next to it. Clone the repository somewhere outside the install directory (the
example uses `/root`); `install.sh` copies from the clone into the install
directory. The loot (database, captures and exports) also has its own namespace,
`/mmc/root/loot/wardrivegotchi/`; if you upgrade from an older build the payload
moves the old `loot/wardrive` directory there once, so your history and level are
kept.

### 4.2 Install the GPS server program

The binary file is a build product. This repository does not contain it. Do one
of these steps:

- Download the binary file from the Releases page of this repository.
- Build the binary file on your computer.

To build the binary file, do one of these commands:

```sh
make -C gps-server build          # Linux or macOS
cd gps-server; .\build.ps1        # Windows
```

The command makes a MIPS soft-float binary file for the Pager. Copy the file to
`payload/mobile2gps/mobile2gps` on the Pager. Then make the file executable with
`chmod +x`.

### 4.3 Install the Python packages

OpenWrt divides the Python standard library into separate packages. The Pager
does not have all the necessary packages. Install them:

```sh
opkg update
opkg -d mmc install python3
```

## 5 Operation

1. Start the Wardrivegotchi payload on the Pager.
2. Push the green button. The payload starts the GPS server. The payload then
   shows the address of the page.
3. Open the address in the browser on your phone.
4. Accept the certificate warning.
5. Push **Start** on the page.

Keep the page in the foreground. Set NoSleep to on.

The position is correct only while the page operates. If the phone locks, the
coordinates become old. Old coordinates are worse than no coordinates, because
old coordinates look correct.

### 5.1 How to examine the GPS function

```sh
pgrep -a gpsd
grep -E "Confirmed|Reclaiming" /tmp/mobile2gps.log
```

The `pgrep` command must show `/dev/pts/N`. The log must contain
`Confirmed gpsd is serving /dev/pts/N`.

Lines that contain `Reclaiming gpsd:` are not a defect. They show that the GPS
server found a different gpsd process and took the port again.

### 5.2 Control from the phone

The phone page can control the scan, so you do not have to touch the Pager. The
controls are on the same page that feeds the GPS, thus the position keeps
updating while you use them.

Turn the controls on:

1. Set `control_token` in `payload/settings.json` to a shared key of your
   choice.
2. Open the GPS page on the phone. A control panel appears below the readout.
3. Type the same key in the Key field.

The panel gives you:

- Start, Pause, Resume and Stop for the scan.
- A live readout: scan state, access point count, channel, elapsed time and the
  GPS fix.
- Export to a Wigle CSV, and upload to Wigle. The upload needs your Wigle keys
  in the settings.
- The band toggles for 2.4, 5 and 6 GHz. A change takes effect on the next scan
  start.

The key is checked on every command. A command with the wrong key is refused.
The key is a shared secret for a private network you control; it is not a
password for an account. If `control_token` is empty, the panel shows but
accepts no commands.

### 5.3 Progression

The payload keeps a player profile that grows as you wardrive. It is a
pwnagotchi-style layer over the scan.

You gain experience for each new unique access point. A find is worth more when
it is notable: an open network, a legacy WEP network, a WPA3 network, or a
captured handshake. Common WPA2 networks are the base. The levels escalate: each
level needs more experience than the one before, thus the early levels come fast
and the later ones are a grind.

You also earn credits, a separate balance you spend in the shop. Credits are not
experience: spending them never lowers your level.

The profile is on the phone page and on the Pager itself. On the Pager, press
RIGHT on the dashboard to open it: level, experience bar, credits, statistics
and the shop. In the shop, UP and DOWN choose an item and A buys it.

The profile panel on the phone page shows the same: your level, an experience
bar, your credits, your statistics, your inventory and the shop.

On the first start, the payload reads the access points already in the database
and sets your level from them, so you do not begin at level 1 for work you have
already done. Credits are not back-dated: they accrue from that point on.

The profile is in `player.json` in the loot directory. You can read it or reset
it by hand.

### 5.4 Avatar and dress-up

The profile has an owl avatar. You spend credits in the shop on items in five
slots: head, eyes, neck, side and feet. The owl wears at most one item per slot.
The slots do not overlap, so items never clip each other. The owl shows on the
phone page and on the Pager, and it changes as you equip and remove items.

**The art is not final.** No finished art ships with this project. Until you add
art, the owl is a plain placeholder that marks which slots are worn, so you can
test the dress-up system now. The art is a drop-in layer: put transparent PNGs in
`payload/avatar_assets/highres/` and `lowres/` with the names in
`avatar_assets/manifest.json`, run `python3 assets/gen_avatar.py`, and the owl
uses your art with no code change. See `payload/avatar_assets/README.md` for the
full contract.

To add a new item, add one line to `payload/items.py` - its id, name, slot, cost
and level. That file is the single item registry: the shop, the inventory and the
avatar all read it, so the item appears everywhere with no other change. Its art
is optional and dropped in as above.

### 5.5 Settings

The file `payload/settings.json` contains the settings. The payload makes this
file at the first start.

| Key | Default | Function |
| --- | --- | --- |
| `gps_source` | `phone` | `phone` uses the GPS server. `serial` uses a USB or serial receiver. |
| `scan_mode` | `stealth` | `stealth` is a passive scan. `active` uses `iw scan`. |
| `scan_5ghz` | `true` | Adds the 5 GHz channels to the scan. |
| `control_token` | `""` | The shared key for the phone control. Empty turns the control off. |
| `phone_dashboard` | `false` | In serial GPS mode, run the phone server as a dashboard only. |
| `gps_stale_secs` | `8` | If no new position arrives in this many seconds, the fix is treated as lost, so access points are not tagged against a frozen position. |
| `gpx_enabled` | `true` | Log the drive route to a GPX track in the exports directory. |
| `gpx_min_move_m` | `8` | Minimum movement in metres between logged track points. |
| `gps_average_positions` | `false` | Store an access point's position as the RSSI-weighted average of its sightings, not the single strongest. |

In phone mode, the payload ignores the GPS device and baud rate settings. The
**Restart gpsd** item in the settings screen does no operation. This is correct
behavior.

### 5.6 GPS source and the phone

The `gps_source` setting decides where the position comes from.

`phone` (the default) uses the bundled server: your phone's browser is the GPS,
and the same page carries the dashboard.

`serial` uses a GPS module on the Pager. The phone is then not needed for a
position. If you still want your phone as a control dashboard, set
`phone_dashboard` to true: the server runs in a control-only mode that does not
touch gpsd, so it does not fight the module, and the page hides its GPS controls
and shows only the dashboard and profile.

### 5.7 GPS server options

| Option | Function |
| --- | --- |
| `-urls` | Shows each address of the server, then stops. |
| `-v` | Records each position and each NMEA sentence in the log. |
| `-max-accuracy` | Sets the accuracy limit in metres. The default value is 100. |

## 6 Wigle data

The payload writes `WigleWifi-1.6` CSV files to
`/mmc/root/loot/wardrivegotchi/exports/`. You can send the files with the payload. You
can also send the files from the Wigle web site.

The output excludes access points that have no position. An access point found
before the first GPS fix is stored at latitude 0, longitude 0 (the Gulf of
Guinea). The payload does not write these access points to the CSV. If it sees
the same access point again after a fix, it fills in the position, and the access
point then appears in the output with its coordinates. Thus you do not have to
clean the file by hand before you send it.

The payload also writes a GPX track of your drive to the same directory
(`track_*.gpx`), unless you set `gpx_enabled` to false. The track uses only
positions with a fix, so it has no 0,0 points.

## 7 Troubleshooting

### 7.1 The dashboard shows No Fix

1. Examine the phone first. The page must be in the foreground. The screen must
   be on.
2. Examine the accuracy value on the page. The page shows `(INVALID)` if the
   accuracy is more than 100 metres.
3. Do the command `pgrep -a gpsd`. If the result is not `/dev/pts/N`, the gpsd
   process of the Pager has the port. The GPS server takes the port again in 20
   seconds.

**Note:** The `pgrep -a` command on the Pager shows only `argv[0]`. Thus a gpsd
process with options shows only as `/usr/sbin/gpsd`. Do not use this command to
identify the gpsd process. Use the log file. You can also send `?DEVICES;` to
gpsd.

### 7.2 The payload stops immediately and the screen looks like a restart

The Pager did not restart. The payload stops the user interface service of the
Pager. The cleanup function of the payload starts the service again. The result
looks the same as a restart.

To find the true error, start the payload manually:

```sh
cd /root/payloads/user/reconnaissance/wardrivegotchi
export PYTHONPATH="$PWD/lib:$PWD:$PYTHONPATH"
export LD_LIBRARY_PATH="/mmc/usr/lib:$PWD/lib:$LD_LIBRARY_PATH"
/etc/init.d/pineapplepager stop
python3 wardrive.py
```

A `ModuleNotFoundError` message shows that an OpenWrt Python package is absent.
Install `python3` as in paragraph 4.3.

### 7.3 The position stops during a drive

The phone locked, or the page went to the background. Set NoSleep to on. Keep the
page in the foreground.

## 8 Licence

The licence is GPL-3.0. Refer to [LICENSE](LICENSE).

This repository contains a modified GPL-3.0 program. Thus the full work is
GPL-3.0. The files that come from the MIT wardrive payload keep the MIT licence.
The directory [LICENSES/](LICENSES/) contains the two licence texts.
