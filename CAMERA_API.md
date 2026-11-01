# Kodak Smart Home Camera — Local API Interoperability Notes

Documented against firmware `03.03.92` (mainos `03.03.92_RC.04`, media
`01.01.14`) on a Kodak pan/tilt camera (UDID model code `006`), from the
camera's behaviour on the local network. These cameras run the
Hubble / CIN platform, so other brands on that platform likely
behave the same.

All examples use placeholder addresses: camera `192.168.1.100`, client
`192.168.1.10`, MAC `AABBCCDDEEFF`.

---

## 1. HTTP API

```
GET http://<camera_ip>/?req=<command>[&param=value...]
```

Plain-text replies of the form `<command>: <value>`. Only `?req=` works on this
firmware; the app's other form (`?action=command&command=`) returns
`400: Not Found!`.

### 1.1 Reply codes

| Reply | Meaning |
|-------|---------|
| `0` | Success (setters) |
| `-1` | Unknown command, or not supported by this model/firmware |
| `-2` | Recognised but refused in the current state (see pan/tilt) |
| `-3` | Invalid value (e.g. `set_resolution&value=1080`) |
| `-5` | No data; for `get_all_pos` it means "pan/tilt not calibrated" |

### 1.2 Status: `get_caminfo`

The main polling call. `&`-separated `key=value` pairs:

| Key | Meaning |
|-----|---------|
| `bat`, `charge`, `charge_dur` | Battery code (below), charging (0/1), a seconds counter that restarts often (not a charge time) |
| `wifi`, `ssid1`, `ssid3`, `localip`, `dnsm`, `dnss` | Wi-Fi signal %, network name(s), IP, DNS servers |
| `res`, `brate`, `flicker`, `isp_idx`, `agc_lvl` | Resolution (480/720), bitrate kbps, anti-flicker Hz, image profile, gain level |
| `flipup`, `fliplr` | Ceiling-mount flip, mirror |
| `ir` | Night vision: 0 auto, 1 on, 2 off |
| `md`, `sd` | Motion / sound detection `enabled:x:sensitivity:y` (sensitivity 1/3/5). For `md`, the 4th field is set once custom motion zones have been written |
| `td`, `lbd` | Temperature alert, low-battery alert (same layout) |
| `tem_float`, `hum_float` | Temperature °C / humidity % (`-273` / `-1` when no sensor) |
| `sdcap`, `sdfree`, `sdatrm`, `sdnoclips` | SD capacity/free MB, auto-delete on, clips kept |
| `storage`, `snapshot_storage` | Save motion clips / snapshots to SD |
| `blue_led_en`, `blue_led_ontime` | Blue LED |
| `lulvol`, `lulla`, `lulla_dur` | Lullaby volume / state |
| `ca`, `mvr` | A stream session is open; motion recording in progress |
| `hw_id`, `soc_ver`, `rp_conn` | Hardware id, SoC version, range-extender state |

**Battery code.** `bat` is not a percentage. It's a two-digit code:

| Part | Meaning |
|------|---------|
| units digit (`bat % 10`) | charge level 0–4, i.e. 0 / 25 / 50 / 75 / 100 % (4 or more is full) |
| tens digit (`bat // 10`) | `1` when plugged in |

So `14` is "full, plugged in" and `4` is "full, on battery"; `13` would be 75 %
and charging. A negative value means the level isn't known. On the test
cameras the value never changed beyond those two readings, because both
batteries were full. (Doorbell-style models may report a battery voltage in a
separate `bat1` field instead; untested here.) `charge_dur` is a seconds
counter that restarts often and isn't a charge time, so it isn't shown.

Other read-only calls: `get_version`, `get_all_versions`
(`recovery=…,mainos=…,media=…`), `get_udid` (24 chars; characters 4–6 are the
model code), `get_mac_address`, `get_wifi_strength`, `get_video_bitrate`,
`get_night_vision`, `get_flicker`, `get_motion_source`,
`get_repeater_status`, `get_setup_log` (JSON), `get_zone_detection`.

### 1.3 Settings

| Command | Parameters | Notes |
|---------|-----------|-------|
| `set_night_vision` | `value=0\|1\|2` | Auto / on / off |
| `set_resolution` | `value=480\|720` | 1080 is rejected (`-3`) |
| `set_video_bitrate` | `value=<kbps>` | App offers 200–1000; camera accepts up to 2000, but 550 (the default) streams best (see §6). Power cuts and the camera's own flow control put it back to 550 |
| `rtscan`, `puscan` | `value=0\|1` | Background Wi-Fi scanning for a Kodak range extender / baby-monitor parent unit (`rtscan`/`puscan` in `get_caminfo`). Not used by the app, but **turning both off halves the stream stalls** (§6). Note: no `set_` prefix |
| `set_flicker` | `value=50\|60` | |
| `set_isp_idx` | `value=0..2` | Image profile |
| `set_flipup` | `value=0\|1` | Ceiling mount |
| `set_motion_source` | `value=0\|1&schedule=<md field 2>` | Motion detection on/off |
| `set_motion_sensitivity` | `value=1\|3\|5` | |
| `set_sound_detection` | `value=0\|1&sensitivity=1\|3\|5&schedule=<sd field 2>` | |
| `set_blue_led` | `enable=0\|1&on_time=180&red_led_affect=0` | |
| `auto_rm_clip` | `value=0\|1&clips=<n>` | |
| `set_motion_storage` / `set_motion_snapshot_storage` | `value=0\|1` | Save clips / snapshots to SD |
| `melody_vol` | `value=0..5` | |
| `melody1` … `melody5`, `melodystop` | `duration=2` | Lullaby playback |
| `set_city_timezone` | `value=<IANA name>` | e.g. `Europe/London` |
| `change_router_info` | `ssid=<b64>&password=<b64>` | Moves a working camera to another network. Both values base64 then URL-encoded |
| `restart_system` | | Soft restart (keeps settings) |

Not supported on this model/firmware (`-1`): `set_framerate`, `set_gop`,
`set_spkmic_volume`, `get_dev_info`, `get_wlan_parameter`.

### 1.4 Motion zones

`get_zone_detection` → `0&value=<base64>&len=<n>`. The value is a
**40 × 23 bit grid** (115 bytes, MSB first, row-major); a set bit means that
cell can trigger motion. Write it back with
`set_zone_detection&value=<base64, URL-encoded>`.

---

## 2. Live stream (VLVL over UDP)

### 2.1 Opening a session

```
GET /?req=get_session_key&mode=local&port1=<our UDP port>&ip=<our IP>&streamname=<MAC>_<random 0-65535>
→ get_session_key: error=200,port1=<camera UDP port>&ip=<camera IP>&key=<32 hex>&sip=&surl=&sp=0&rn=<24 hex>
```

- `key`: hex-decode to the **per-session** AES-128 key (it changes every session).
- `port1` in the reply is the **camera's** UDP port; commands and ACKs go there.
- The stream name must be unique per session, as the app does. The camera
  keeps old sessions alive for ~30 s and addresses mode commands by name.
- One session at a time; while another is alive the reply is
  `error=500,relay_server_ip_not_found`.

### 2.2 Packet header (20 bytes, big-endian)

```
0  4  "VLVL"
4  2  packet type
6  4  capture timestamp of the frame, milliseconds (camera clock; audio uses the same clock)
10 2  number of packets in the frame
12 4  seqS — seqC of the first packet of this frame
16 4  seqC — this packet's sequence number (shared by all types)
20 …  payload
```

A frame is complete once its packet count has arrived; release frames in
order. The camera captures at a steady 15 fps (66–67 ms steps) but its Wi-Fi
delivers them in bursts (§6), so players should pace playback by the capture
timestamp rather than arrival time.

`seqS == seqC` marks a frame's first packet. Reassemble a frame by joining
payloads in `seqC` order.

### 2.3 Packet types

| Type | Direction | Content |
|------|-----------|---------|
| `0x0D` | cam → client | H.264 keyframe, Preview mode |
| `0x0A` | cam → client | H.264 keyframe (SPS + PPS + IDR), Full mode |
| `0x0C` | cam → client | H.264 P-frame, Full mode |
| `0x19` | cam → client | Audio, G.722 64 kbit/s (16 kHz mono), 512 bytes |
| `0x1E` | client → cam | Text command (§3) |
| `0x1F` | cam → client | Command reply (§3) |
| `0x20`, `0x21` | cam → client | 34-byte stream-control probes (no seq fields) |
| `0x32` | client → cam | Selective ACK (§2.5) |

### 2.4 Encryption

AES-128 with the session key:

- **Video** (`0x0A/0x0C/0x0D`): *sparse*. Decrypt one 16-byte block every
  `0x410` (1040) bytes of the reassembled frame, from offset 0, AES-ECB.
- **Audio** (`0x19`): *dense*. Every whole 16-byte block, AES-ECB.
- **Commands/replies**: AES-CBC, zero IV, zero padding.

### 2.5 ACKs (required)

The camera paces the stream on ACKs. Without them
it stops after a couple of frames. Every ~50–100 ms send:

```
"VLVL" 00 32  <first missing seqC, BE32>  <336 bytes: 1 if seqC=base+i received>
```

### 2.6 Stream modes

Request after opening (over the command channel, §3):
`p2p_ses_mode_set&value=<mode>&streamname=<the session's stream name>`

| Mode | Name | Result on test camera |
|------|------|-----------------------|
| 0 | Preview (default) | ~1 fps keyframes only |
| 2 | IFrame only | keyframes only |
| **3** | **Full** | **~11 fps keyframes + P-frames, plus audio** |
| 5 | Extra | ~8 fps, lower bitrate |

### 2.7 Video format

H.264 **High profile, level 4.0, CABAC**, 1280×720, sent in-band at the start of
every keyframe:

- SPS `67 64 00 28 ac e8 05 00 5b 90` (`Z2QAKKzoBQBbkA==`)
- PPS `68 ee 3c 30` (`aO48MA==`)
- SDP `profile-level-id=640028`

Keyframes arrive roughly every 1–1.5 s; frame rate varies, so timestamp by
wall clock.

---

## 3. Command channel (inside the session)

The same text commands as HTTP, sent through the open UDP session. **Pan/tilt
only works here** (over HTTP motor commands answer `-2` and do nothing).

```
request : "VLVL" 00 1E <seq BE32> AES-CBC(zero IV, zero-padded)( <seq BE32> "req=<command>&<params>" )
reply   : "VLVL" 00 1F <seq BE32> <len BE16> AES-CBC( "<command>: <value>" )
```

Commands travel over UDP, so resend a request (up to ~4 times) until a reply arrives.

### 3.1 Pan & tilt

| Command | Params |
|---------|--------|
| `motor_left` / `motor_right` / `motor_up` / `motor_down` | `time=<current epoch ms>` |
| `motor_stop` | `time=<current epoch ms>` |
| `motor_calibration` | `mode=1` |
| `get_all_pos`, `go_pos`, `set_pos`, `remove_pos` | presets: `pos_id=1..5`, plus `moving_mode=0` / `stop_time=500` |

- Treat motor commands as fire-and-forget and **repeat the direction
  every ~0.5 s while held**, then send `motor_stop`. The first command of a
  sequence answers `-2` and later ones are echoed back, but the camera moves
  either way.
- Pan/tilt models by UDID model code: `006`, `008`, `018`.
- **Calibration:** `get_all_pos: 0` means calibrated; `-5` means not. The test
  camera stayed uncalibrated: `motor_calibration` answered `-2` and a soft
  restart, a first connection after boot and a full power cycle didn't
  calibrate it. An uncalibrated camera **doesn't stop at its mechanical ends**,
  so clients should cap how long a move runs. The companion KodaxWeb app stops 0.9 s after the
  last repeat, caps a hold at 3 s, and supports software end-stops. Presets
  didn't work while uncalibrated.

---

## 4. First-time setup (pairing mode)

A camera in pairing mode creates a Wi-Fi network `KodakCam-…` (older:
`Camera-…`) and answers at `192.168.193.1` (some models `192.168.0.254` or
`192.168.222.1`). The steps below are the local part of pairing; the cloud
registration steps are no longer needed:

1. `get_udid`, `get_version`, `get_caminfo` (sanity checks).
2. `set_flicker&value=50|60`.
3. Generate a random AES-128 key; RSA-PKCS1v1.5 encrypt it with the RSA public
   key that ships with the official mobile app (not included here); send `set_sec_type&value=<hex>`.
4. `set_server_auth&value=<token>&timezone=<±HH.MM>` (the cloud token is
   meaningless now) and `set_city_timezone&value=<IANA name>`.
5. Wi-Fi details: build the fixed-width string below, then AES-CBC encrypt with IV
   `"cinatic_2018"` padded with NULs to 16 bytes (zero-pad to 16, then PKCS#5),
   hex-encode, and send `set_nwk_info_v2&setup=<hex>`:

```
"1" "00" <mode: 2=WPA, 0=open> <key index "0"> "0"
<len(b64 ssid) %03d> <len(b64 password) %02d> "00" "00" "00" "0" "00" "00"
<b64 ssid> <b64 password>
→ then URL-encode the whole string before encrypting
```

The camera reboots onto the new network. The companion KodaxWeb app implements this, but it
hasn't been tested end-to-end against a camera in pairing mode.

---

## 5. VLVL → RTSP bridge (Home Assistant integration)

Home Assistant's stream component needs RTSP, so the integration runs a small
RTSP/RTP server on `127.0.0.1` (OS-assigned port), opens a VLVL session in
Full mode, and forwards each access unit as RTP/H.264 (RFC 6184, FU-A above
1400 bytes, payload type 96, 90 kHz timestamps taken from the camera's capture
times). New clients start at the next keyframe; thumbnails use the last
keyframe.

---

## 6. Stream quality notes (test camera)

**Wi-Fi stalls.** The camera's radio regularly goes quiet for ~0.5 s (HTTP
and video together), then delivers the held-back frames in a burst; nothing
is lost and capture timestamps continue evenly underneath. With background
scanning on (`rtscan=1`, `puscan=1`) there were 12 such stalls per 30 s; with
both off, 5, and ping dropped from spikes of ~400 ms to a flat 3–4 ms.

**Skipped frames.** The camera's flow control sometimes encodes a P-frame and
then never sends it (the H.264 `frame_num` jumps while every sent packet
arrives). Later P-frames then reference a picture the client never got, which
shows as smearing until the next keyframe (~1 s). Its own app worked around
this by skipping to the next keyframe. Skips per 30 s by bitrate:

| Bitrate | 400 | **550** (default) | 700 | 850 | 1000 | 1200 |
|---------|-----|---------|-----|-----|------|------|
| Skipped frames | 13 | **12–15** | 16–27 | 29 | 27 | 49 |

So **550 kbps is the best setting**; higher bitrates look sharper but smear
far more often. Even at 550 about 1 frame in 25 is skipped. Pausing until the
next keyframe instead of smearing would freeze the picture ~30% of the time at
these rates.

Frame rate (15 fps capture) and keyframe interval can't be set
(`set_framerate`/`set_gop` → `-1`).

---

## 7. Still unknown

| Item | Status |
|------|--------|
| What re-enables pan/tilt calibration | `-2` in every state tried |
| Two-way audio (talkback) | Not yet worked out |
| SD-card clip download | Not found |
| `0x20`/`0x21` probe contents | 16 encrypted bytes after the MAC; not decoded |
| Remote (cloud/relay) modes | Not investigated; `mode=local` is all that's needed on the LAN |
