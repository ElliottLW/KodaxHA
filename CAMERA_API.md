# Kodak Smart Home Camera — Reverse-Engineered API Reference

Documented against firmware `03.03.92` on a **Kodak W101 / W121**.
All API calls are plain HTTP GET to `http://<camera_ip>/`.

---

## 1. HTTP API

All endpoints follow the same pattern:

```
GET http://<camera_ip>/?req=<command>[&param1=val1&param2=val2...]
```

Responses are plain text in the format `<command>: key1=val1&key2=val2&...`  
On error the value portion is `-1`.

### 1.1 Read-Only (Polling)

#### `get_caminfo`
Returns the primary device state. This is the main polling endpoint.

```
GET http://<ip>/?req=get_caminfo
```

**Response fields** (all string values, `&`-delimited):

| Key | Type | Description |
|-----|------|-------------|
| `bat` | int 0–100 | Battery percentage |
| `wifi` | int 0–100 | WiFi signal strength % |
| `ca` | `0`/`1` | Camera active (live view open) |
| `charge` | `0`/`1` | Currently charging |
| `charge_dur` | int (minutes) | Time spent charging |
| `ir` | `0`/`1`/`2` | Night vision: 0=auto, 1=on, 2=off |
| `res` | `480`/`720` | Current video resolution |
| `flipup` | `0`/`1` | Orientation: 0=normal, 1=ceiling mount |
| `brate` | int (kbps) | Current video bitrate |
| `sdcap` | int (MB) | SD card total capacity (-1 if absent) |
| `sdfree` | int (MB) | SD card free space |
| `sdatrm` | `0`/`1` | Auto-remove old clips enabled |
| `mvr` | `0`/`1` | Motion recording currently active |
| `md` | string | Motion detection config (see below) |
| `sd` | string | Sound detection config (see below) |
| `blue_led_en` | `0`/`1` | Blue LED enabled |

**`md` field format**: `enabled:schedule:sensitivity:unknown`  
Example: `1:0:3:0` = enabled, no schedule, medium sensitivity (3), unknown=0  
Sensitivity values: 1=low, 3=medium, 5=high

**`sd` field format**: same structure as `md`

---

#### `get_temp_humid`
Returns environmental sensor readings. Only present on cameras with the
built-in sensor (W121). Returns `-273` for temperature and `-1` for humidity
if no sensor is fitted.

```
GET http://<ip>/?req=get_temp_humid
```

| Key | Type | Description |
|-----|------|-------------|
| `tem` | string | Temperature in °C (may be integer string) |
| `hum` | string | Humidity in % |

The integration parses these as `tem_float` and `hum_float` after casting.

---

#### `get_mac_address`
Returns the camera's hardware MAC address. Used to construct the VLVL stream name.

```
GET http://<ip>/?req=get_mac_address
```

**Response**: `get_mac_address: AABBCCDDEEFF`  
(12 hex chars, no separators)

---

#### `get_version`
Returns firmware version string.

```
GET http://<ip>/?req=get_version
```

---

#### `get_wifi_strength`
Returns current WiFi signal as a percentage (also available in `get_caminfo`).

```
GET http://<ip>/?req=get_wifi_strength
```

---

### 1.2 Control Commands

All control commands return HTTP 200 on success. No response body is needed.

#### Night Vision
```
GET http://<ip>/?req=set_night_vision&value=<0|1|2>
```
Values: `0`=auto, `1`=always on, `2`=always off

---

#### Video Resolution
```
GET http://<ip>/?req=set_resolution&value=<480|720>
```

---

#### Camera Orientation (Flip)
```
GET http://<ip>/?req=set_flipup&value=<0|1>
```
Values: `0`=normal, `1`=ceiling mount (180° flip)

---

#### Motion Detection
```
GET http://<ip>/?req=set_motion_source&value=<0|1>&schedule=0
```
`value=1` enables, `value=0` disables. `schedule=0` means always active.

---

#### Motion Detection Sensitivity
```
GET http://<ip>/?req=set_motion_sensitivity&value=<1|3|5>
```
Values: `1`=low, `3`=medium, `5`=high

---

#### Sound Detection
```
GET http://<ip>/?req=set_sound_detection&value=<0|1>&sensitivity=<1|3|5>&schedule=0
```

---

#### Blue LED
```
GET http://<ip>/?req=set_blue_led&enable=<0|1>&on_time=180&red_led_affect=0
```
`on_time` is in seconds. `red_led_affect=0` leaves the red LED unchanged.

---

#### Auto-Remove Old Clips
```
GET http://<ip>/?req=auto_rm_clip&value=<0|1>&clips=10
```
`clips=10` = keep the last 10 clips before auto-removing.

---

#### Melody / Siren
```
GET http://<ip>/?req=melody1&duration=2
GET http://<ip>/?req=melody2&duration=2
GET http://<ip>/?req=melody3&duration=2
GET http://<ip>/?req=melody4&duration=2
GET http://<ip>/?req=melody5&duration=2
GET http://<ip>/?req=melodystop
```
`duration` unit is unknown — value `2` plays for approximately 10 seconds.

---

#### System Restart
```
GET http://<ip>/?req=restart_system
```
Camera reboots immediately. No response body.

---

## 2. VLVL Live Stream Protocol

The camera does **not** serve RTSP or MJPEG directly. Live video is delivered
over a proprietary UDP P2P protocol named **VLVL** (magic bytes `0x56 0x4C 0x56 0x4C`).

### 2.1 Session Establishment

A stream session is requested via HTTP before any UDP packets are sent:

```
GET http://<ip>/?req=get_session_key&mode=local&port1=<UDP_PORT>&ip=<OUR_IP>&streamname=<MAC>_8
```

| Parameter | Description |
|-----------|-------------|
| `mode` | Always `local` for LAN access |
| `port1` | UDP port the client is listening on |
| `ip` | Client's local IP (the camera sends packets here) |
| `streamname` | `<MAC>_8` — MAC address (no separators) + `_8` suffix |

**Success response** (plain text):
```
get_session_key: error=200,port1=<PORT>&ip=<CAMERA_IP>&key=<HEX_KEY>&sip=&surl=&sp=0&rn=<NONCE>
```
`error=200` = accepted. The camera immediately begins pushing UDP packets to `<OUR_IP>:<port1>`.

**Failure**: response body contains `error=` with a non-200 code.

> The session is not persistent — the camera stops sending after ~30 seconds of
> no activity. The integration requests a new session on each PLAY command.

---

### 2.2 VLVL UDP Packet Format

Each UDP datagram has a **42-byte header** followed by raw H264 Annex B payload.

```
Offset  Size  Type        Description
------  ----  ----------  ---------------------------------------------------
 0      4     bytes       Magic: 0x56 0x4C 0x56 0x4C  ("VLVL")
 4      2     uint16 BE   Packet type: 0x000D = video, 0x0020 = control/keepalive
 6      2     uint16 BE   Sub-type / flags (not decoded)
 8      4     uint32 BE   Frame timestamp / identifier
12      4     uint32 BE   seqS — packet index of the START packet of this frame
16      4     uint32 BE   seqC — packet index of THIS packet (absolute, monotonic)
20     22     bytes       Session data (camera-specific, not needed for decoding)
42      *     bytes       H264 Annex B payload (partial frame data)
```

**Frame detection rule**: `seqS == seqC` means this packet is the **first** packet
of a new H264 IDR frame. All subsequent packets with the same `seqS` value
(and increasing `seqC`) belong to the same frame.

**Packet ordering**: UDP delivers packets mostly in order on a LAN but
out-of-order delivery does occur. Packets must be **sorted by `seqC`** before
concatenating their payloads, otherwise the H264 bitstream is corrupted.

---

### 2.3 H264 Codec Parameters

The camera streams **H264 Annex B**, IDR-only (keyframe-only — no P-frames between
IDRs). The camera **never sends SPS or PPS** NAL units in the UDP stream; they
must be injected by the client before each frame.

**Confirmed SPS/PPS** (W101/W121, 1280×720, Baseline Level 3.1, CAVLC):

| NAL Unit | Raw bytes (hex) | Annex B (with start code) |
|----------|-----------------|--------------------------|
| SPS | `67 42 C0 1F ED 00 A0 0B 62` | `00 00 00 01 67 42 C0 1F ED 00 A0 0B 62` |
| PPS | `68 CE 38 80` | `00 00 00 01 68 CE 38 80` |

Base64 (for RTSP SDP `sprop-parameter-sets`):
- SPS: `Z0LAH+0AoAti`
- PPS: `aM44gA==`

**SDP profile-level-id**: `42C01F`

**RTP clock**: 90 kHz. At ~15 fps the timestamp increment per frame is ~6000.

**Decoded resolution**: 1280×720 (confirmed via VLC verbose log "Received first picture").

---

### 2.4 Frame Assembly (Full Algorithm)

```python
frame_packets: dict[int, bytes] = {}   # seqC -> payload
frame_seq_start: int = -1

for each UDP packet:
    if packet_type != 0x000D: continue  # not video
    seqS = big_endian_uint32(packet[12:16])
    seqC = big_endian_uint32(packet[16:20])
    payload = packet[42:]

    if seqS == seqC:  # new frame starting
        if frame_packets:
            # Yield previous frame (sorted by seqC)
            raw = b"".join(frame_packets[k] for k in sorted(frame_packets))
            emit(SPS_ANNEX_B + PPS_ANNEX_B + raw)
        frame_packets = {}
        frame_seq_start = seqS

    if seqS == frame_seq_start:
        frame_packets[seqC] = payload
```

---

### 2.5 Typical Frame Sizes

| Resolution | Packets per frame | Frame size |
|------------|-------------------|------------|
| 720p (1280×720) | ~20–30 UDP packets | ~25–32 KB |
| 480p | ~10–15 UDP packets | ~12–18 KB |

Each UDP payload is up to ~1450 bytes (standard LAN MTU minus headers).

---

## 3. RTSP Bridge (Integration Implementation)

Since HA's stream integration requires RTSP, the integration runs a minimal
asyncio RTSP/RTP server on `127.0.0.1` at an OS-assigned port.

### Flow

```
HA frontend / stream integration
        |
        | TCP  RTSP/RTP (RFC 2326 + RFC 6184)
        v
KodaxRTSPServer  (127.0.0.1:<random_port>)
        |
        | HTTP  get_session_key
        v
Kodak camera  (10.0.x.x)
        |
        | UDP  VLVL packets
        v
VLVLFrameReceiver  (reassemble + sort)
        |
        | RTP/H264 over TCP interleaved
        v
HA stream integration  (HLS / WebRTC proxy)
```

### RTSP Subset Implemented

| Method | Notes |
|--------|-------|
| `OPTIONS` | Returns supported methods |
| `DESCRIBE` | Returns SDP with H264 profile and `sprop-parameter-sets` |
| `SETUP` | Forces TCP interleaved transport (channels 0-1); returns `Session:` header |
| `PLAY` | Opens VLVL session, begins forwarding frames as RTP; returns `Session:` + `RTP-Info:` |
| `TEARDOWN` | Closes VLVL session |

### SDP

```
v=0
o=- 0 0 IN IP4 127.0.0.1
s=KodaxHA Camera
c=IN IP4 127.0.0.1
t=0 0
m=video 0 RTP/AVP 96
a=control:trackID=0
a=rtpmap:96 H264/90000
a=fmtp:96 packetization-mode=1;profile-level-id=42C01F;sprop-parameter-sets=Z0LAH+0AoAti,aM44gA==
```

`Content-Base:` is included in the DESCRIBE response so clients resolve
`a=control:trackID=0` to the correct absolute SETUP URL.

### RTP Packetization

- NALUs <= 1400 bytes: single NAL unit packet (RFC 6184 §5.6)
- NALUs > 1400 bytes: FU-A fragmentation (RFC 6184 §5.8)
- All packets use dynamic payload type 96
- Timestamp clock: 90 kHz, incremented by 6000 per frame (~15 fps)

---

## 4. Known Unknowns / Not Yet Reversed

| Feature | Status |
|---------|--------|
| Cloud relay (non-local mode) | Not investigated — `mode=local` is sufficient |
| Audio stream | Not present in VLVL packets observed |
| `0x0020` control packets | Seen in capture, content not decoded |
| SD card clip download | HTTP endpoint likely exists, not found |
| Push notifications / event subscription | Not investigated |
| Two-way audio | Hardware supports it, API endpoint unknown |
| `streamname` suffix `_8` meaning | Unknown — possibly stream index |
| `sp`, `surl`, `sip`, `rn` fields in session response | Unknown |
| Firmware update mechanism | Not investigated |
| 480p vs 720p SPS/PPS | Only 720p confirmed; 480p SPS/PPS not captured |
