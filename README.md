# KodaxHA — Home Assistant Integration

A HACS-installable custom integration for **Kodak Smart Home cameras** after Kodak discontinued their cloud service. Communicates directly with the camera over your local network — no cloud, no account, no subscription.

---

## Features

- 📷 **Camera entity** — live H264 video via built-in VLVL→RTSP bridge; JPEG snapshots via ffmpeg; full HomeKit support
- 📊 **Sensors** — battery, WiFi signal, temperature, humidity, SD card usage, bitrate
- 🔔 **Binary sensors** — charging status, camera active, motion recording
- 🔀 **Switches** — motion detection, sound detection, blue LED, auto-remove old clips
- 🎛️ **Selects** — night vision, video resolution, motion sensitivity, camera orientation
- 🎵 **Buttons** — play melody 1–5, stop melody, restart camera
- 🃏 **Lovelace card** — self-registering dashboard card with all controls in one panel
- ⚙️ **Zero re-add config** — stream/snapshot URLs and poll interval changeable via *Configure* at any time

---

## Requirements

| Requirement | Detail |
|-------------|--------|
| Home Assistant | 2024.1.0 or newer |
| HACS | Any recent version |
| Camera | Kodak Smart Home camera (W101, W121, etc.) on your local network |
| Network | HA and the camera must be on the same subnet |

---

## Installation

### Via HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ElliottLW&repository=KodaxHA&category=integration)

1. Click the button above, **or** manually add this repository in HACS:
   - Open HACS in Home Assistant
   - Go to **Integrations**
   - Click the three-dot menu (⋮) in the top-right corner and select **Custom repositories**
   - Enter `https://github.com/ElliottLW/KodaxHA` as the repository URL and select **Integration** as the category
   - Click **Add**
2. Search for **KodaxHA** in HACS and click **Download**
3. Restart Home Assistant

### Manual

Copy the `custom_components/kodaxha/` folder into your HA config directory (alongside `configuration.yaml`), then restart.

---

## Setup

1. **Settings → Integrations → Add Integration → KodaxHA**
2. Enter your camera's local IP address (e.g. `192.168.178.36`)
3. Optionally set the poll interval (default 30 s)
4. Click **Submit** — HA will verify the camera is reachable

A **KodaxHA Camera** device appears with all entities automatically. The Lovelace card is also registered as a frontend resource — no extra YAML needed.

---

## Lovelace Card

Add the card to any dashboard:

```yaml
type: custom:kodaxha-card
camera_ip: 192.168.178.36
```

The card shows:

| Section | Content |
|---------|---------|
| Header | Camera name, IP, online/offline indicator |
| Feed | Live image (when stream/snapshot configured) |
| Stats | Battery, WiFi, temperature, humidity, SD usage |
| Detection | Motion & sound toggles, sensitivity selector |
| Settings | Night vision, resolution, orientation, blue LED |
| Melodies | Play melody 1–5, stop button |
| System | Restart camera button |

> If the feed shows a placeholder, ensure `ffmpeg` is installed on the HA host (see [Live View](#live-view) below).

---

## Live View

KodaxHA includes a built-in **VLVL → RTSP bridge** that enables live video directly from the camera with no cloud, no port forwarding, and no additional software required.

### How it works

Kodak cameras stream H264 video using a proprietary UDP P2P protocol called **VLVL**. The integration:

1. Fetches the camera's MAC address automatically
2. Starts a minimal RTSP server bound to `localhost` (chosen automatically, no config needed)
3. On each request, opens a VLVL session to the camera and forwards H264 NALUs as RTP/H264
4. HA's built-in stream component proxies the RTSP stream as HLS / WebRTC to the frontend

The result: **the Live View card "just works"** after adding the integration, as long as HA and the camera are on the same network.

### Snapshots (thumbnails)

Thumbnails are captured by grabbing one H264 frame from the VLVL stream and decoding it to JPEG using **ffmpeg**. For this to work, `ffmpeg` must be installed on the system running Home Assistant:

| HA install type | ffmpeg location |
|-----------------|-----------------|
| Home Assistant OS (HAOS) | ✅ Pre-installed |
| Home Assistant Supervised | ✅ Typically included |
| Home Assistant Core (venv) | Install with `apt install ffmpeg` or equivalent |
| Docker | Add `ffmpeg` to your Docker image or use HAOS |

If ffmpeg is unavailable, the stream still works but the thumbnail/snapshot will be blank. You can also set a custom **Snapshot URL** under *Settings → Integrations → KodaxHA → Configure* to use a static image URL as the thumbnail.

### Manual override

If you want to use an external RTSP URL (e.g. from another integration or proxy) instead of the built-in bridge:

1. **Settings → Integrations → KodaxHA → Configure**
2. Enter your **RTSP Stream URL** and/or **Snapshot URL**
3. Save — the built-in RTSP server will be bypassed when a manual URL is set


---

## HomeKit via Homebridge

The built-in RTSP bridge exposes a standard RTSP stream, so HomeKit works with either of the two paths below.

### Option A — via Home Assistant (easiest)
Install the **HomeKit Bridge** integration in HA (`Settings → Integrations → HomeKit Bridge`). The `camera.kodak_camera_live_view` entity is exposed to HomeKit automatically alongside all other KodaxHA entities.

### Option B — via homebridge-camera-ffmpeg (direct)
In Homebridge, add a camera source pointed at the RTSP URL that HA logs on startup (check **Settings → System → Logs** for `KodaxHA (%s): RTSP server started at rtsp://127.0.0.1:…`):

```json
{
  "name": "Kodak Camera",
  "videoConfig": {
    "source": "-i rtsp://127.0.0.1:PORT/",
    "maxFPS": 15,
    "maxBitrate": 600,
    "vcodec": "copy"
  }
}
```

---

## Available Entities

| Entity | Type | Description |
|--------|------|-------------|
| `camera.kodak_camera_live_view` | Camera | Live H264 stream via VLVL→RTSP bridge + JPEG snapshots via ffmpeg |
| `sensor.kodak_camera_battery_level` | Sensor | Battery % |
| `sensor.kodak_camera_wifi_signal` | Sensor | WiFi signal % |
| `sensor.kodak_camera_temperature` | Sensor | °C (if sensor present) |
| `sensor.kodak_camera_humidity` | Sensor | % (if sensor present) |
| `sensor.kodak_camera_sd_card_capacity` | Sensor | MB |
| `sensor.kodak_camera_sd_card_free_space` | Sensor | MB free |
| `sensor.kodak_camera_video_bitrate` | Sensor | kbps |
| `sensor.kodak_camera_charge_duration` | Sensor | Minutes |
| `binary_sensor.kodak_camera_charging` | Binary | Charging? |
| `binary_sensor.kodak_camera_active` | Binary | Camera active? |
| `binary_sensor.kodak_camera_motion_recording` | Binary | Currently recording? |
| `switch.kodak_camera_motion_detection` | Switch | Enable/disable motion |
| `switch.kodak_camera_sound_detection` | Switch | Enable/disable sound |
| `switch.kodak_camera_blue_led` | Switch | LED on/off |
| `switch.kodak_camera_auto_remove_old_clips` | Switch | Auto-remove SD clips |
| `select.kodak_camera_night_vision` | Select | Auto / On / Off |
| `select.kodak_camera_video_resolution` | Select | 480p / 720p |
| `select.kodak_camera_motion_sensitivity` | Select | Low / Medium / High |
| `select.kodak_camera_camera_orientation` | Select | Normal / Ceiling Mount |
| `button.kodak_camera_restart_camera` | Button | Restart |
| `button.kodak_camera_play_melody_1` … `_5` | Button | Play melody |
| `button.kodak_camera_stop_melody` | Button | Stop melody |

---

## Troubleshooting

**"No entities found" in the card**
→ Ensure the integration loaded without errors. Check **Settings → System → Logs** for `kodaxha`.

**Camera shows offline / unavailable**
→ Confirm HA can reach the camera: `ping 192.168.178.36` from your HA host. Also check the camera hasn't changed IP — assign a DHCP reservation in your router for the camera's MAC address.

**Lovelace card not appearing in card picker**
→ If HA is in YAML mode, manually add the resource to your `configuration.yaml`:
```yaml
lovelace:
  resources:
    - url: /kodaxha/kodaxha-card.js
      type: module
```

**Temperature / humidity show as unavailable**
→ Your camera model doesn't have an environment sensor. These entities are automatically hidden when the camera reports no sensor data.

---

## Credits

- Camera HTTP API reverse-engineered from [kairoaraujo/kodak-smart-home](https://github.com/kairoaraujo/kodak-smart-home) and community findings in [issue #16](https://github.com/kairoaraujo/kodak-smart-home/issues/16)
- VLVL P2P protocol reverse-engineered by Elliott L-W through UDP packet analysis; SPS/PPS parameters verified with VLC (H264 baseline 1280×720)
- Built on top of the original Kodak Smart Home mobile app architecture (PerimeterSafe SDK)

## Licence

See [LICENSE](../LICENSE)
