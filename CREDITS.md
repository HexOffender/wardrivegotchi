# Credits and source of the software

This documentation uses ASD-STE100 Simplified Technical English.

## 1 Introduction

This repository is not original work. It combines two projects. It adds the code
that makes the two projects operate together.

HexOffender maintains this combined fork. The two authors below wrote almost
all of the original software. This fork adds the integration, some corrections,
the phone control panel, and one visual style. As the fork adds more features it
diverges further from both sources, but their work stays credited here for as
long as any of it remains.

## 2 Source projects

### 2.1 mobile2gps by Ryan Pohlner (@Spectracide)

<https://github.com/ryanpohlner/mobile2gps> — **GPL-3.0**

Support Ryan Pohlner: <https://ko-fi.com/ryanpohlner>

The directory [`gps-server/`](gps-server/) contains a fork of mobile2gps.

Ryan Pohlner made the full design. The design has these steps. The server sends
an HTTPS page. The page reads the browser Geolocation API. The server changes
each position into an NMEA GPRMC sentence. The server writes the sentence to a
pseudo-terminal. The gpsd process reads the pseudo-terminal as a usual serial
GPS receiver.

The certificate function, the pseudo-terminal method, the NMEA conversion and the
web page are all from that project.

mobile2gps gives credit to these projects:

- **iphone-gpsd** by Balint Seeber — <https://spench.net/drupal/software/iphone-gps>
- **NoSleep.js** by Rich Tibbett — <https://github.com/richtr/NoSleep.js> (MIT)

### 2.2 pineapple_pager_wardrive by brAinphreAk

<https://github.com/brainphreak/pineapple_pager_wardrive> — **MIT**

brAinphreAk's website: <https://www.brainphreak.net>

Support brAinphreAk: <https://ko-fi.com/brainphreak>

The directory [`payload/`](payload/) contains a fork of this project.

brAinphreAk wrote all of these functions:

- the dashboard
- the passive scanner and the active scanner
- the beacon parser and the RSN/WPA parser
- the handshake capture function
- the SQLite database
- the web server
- the Wigle export function and the Wigle upload function

This fork changes some of these files and adds new ones. It adds no new scan
functions: the scanning, parsing and capture are all his.

## 3 Changes in this fork

### 3.1 Changes in the GPS server

**The GPS server now monitors gpsd.** Before, it started gpsd one time. The Pager
operates its own gpsd process with no GPS device. The Pager starts that process
again each time its services start. The wardrive payload stops and starts those
services. The gpsd process of the Pager then takes port 2947. It answers clients
but never reports a position. Thus the position stops during a drive. The GPS
server now examines the port every 20 seconds. If a different gpsd process has
the port, the GPS server takes the port again.

**The GPS server now examines gpsd at start.** It sends `?DEVICES;` to gpsd and
compares the answer with its own device. Before, a successful `fork` operation
was the only test.

**The GPS server no longer writes to the pseudo-terminal from the HTTP handler.**
If no process reads the pseudo-terminal, a write operation does not stop. Write
deadlines have no result on a pseudo-terminal master. Thus one defective gpsd
process stopped the HTTP handler. The GPS server now puts the sentences in a
queue with a maximum length. One dedicated goroutine writes them. If no process
reads the device, the server discards the sentences and counts them.

**The certificate covers each address of the Pager.** Before, it covered only
`172.16.52.1`. Thus a wired connection or a tethered connection caused a second
browser warning about the host name.

**NMEA times are now UTC.** Before, the code used local time. Thus each sentence
contained the time zone offset of the Pager.

**The log has levels and is quiet by default.** The `/tmp` directory is in RAM on
the Pager. A log of each sentence for a long drive uses memory that the scanner
needs. The `-v` option gives the full log. The default log shows one summary line
each minute.

**New options.** The `-urls` option shows each address of the server. The
`-max-accuracy` option sets the accuracy limit.

**New file structure.** One file became `main.go`, `cert.go`, `gpsd.go`,
`nmea.go`, `urls.go` and `log.go`. The fork adds tests.

### 3.2 Changes in the payload

**The payload starts and stops the GPS server.** The payload starts the server
after it stops the pager service. This sequence is important. The stop operation
is one of the causes that starts the gpsd process of the Pager. The payload stops
the GPS server only if the payload started it.

**New setting `gps_source`.** The default value is `phone`. In phone mode,
`GpsReader` does not control gpsd. It waits for gpsd. The function
`restart_gpsd` does no operation.

This is important. All the functions that stop gpsd use that one method. This
includes the device selection screen and the **Restart gpsd** item. In phone
mode, gpsd is connected to a pseudo-terminal. A restart operation would connect
gpsd to `/dev/ttyACM0`. That device does not exist on this equipment. Thus a
restart operation would stop a correct GPS function.

Serial mode has no changes.

**The Wigle test now reads the last `TPV` object.** Before, it read the last line
from gpsd. That line is frequently a `SKY` object. A `SKY` object has no
coordinates. Thus the test showed `no fix` when the position was correct.

**The screen colours** use the same palette as the phone page. The file
`palette.py` holds them. Before, three files declared the same colours as
literals, thus a change to one screen did not reach the others.

**The menus use filled blocks for the selected item.** The accent colour is a
fill and not a text colour: as text on the background it measures 1.9:1. Thus a
screen cannot show emphasis with colour. A filled block is the same mark as the
buttons on the phone page. The file `blocks.py` draws them.

**The phone page can control the scan.** The page carries a control panel:
start, pause, resume, stop, export, Wigle upload, and the band toggles, with a
live status readout. The commands reach the payload through the GPS server,
which relays them over localhost, because a browser will not let the HTTPS page
call the payload's plain-HTTP port. The panel needs a shared token, set in
settings.json, and is off until one is set. The GPS server carries this as a
generic, off-by-default proxy flag, thus on its own it has no control feature
and no dependency on the payload.

**A progression framework.** The payload keeps a player profile: levels,
experience, credits, an inventory and a shop. You gain experience for each new
unique access point, weighted by the find, and the levels escalate. This is new
work in the fork, in `player.py`, and it is the framework for a pwnagotchi-style
avatar and rewards that come later. The shop items are placeholders for now.

## 4 Third-party files

The `install.sh` script gets these files from the repository of brAinphreAk:

- `lib/libpagerctl.so`
- `lib/pagerctl.py`
- `fonts/title.TTF`
- `fonts/menu.ttf`

This repository does not contain those files. The files are in an MIT
repository. But an MIT licence does not give rights that the author did not have.
The `libpagerctl.so` library looks like a Hak5 library and not the work of
brAinphreAk. Thus this repository gets the files at installation. This method
keeps the question with the source project. The installation is not more
difficult.

## 5 Licence

The licence is GPL-3.0. This repository contains a modified GPL-3.0 program.
Thus the full work is GPL-3.0.

The files that come from the MIT wardrive payload keep the MIT licence. The file
[`LICENSES/wardrive-MIT.txt`](LICENSES/wardrive-MIT.txt) contains that notice.
The directory [`LICENSES/`](LICENSES/) contains the two licence texts. Refer to
[`LICENSE`](LICENSE).
