# KodaxHA — Home Assistant Integration

A HACS-installable custom integration for **Kodak Smart Home cameras** after Kodak discontinued their cloud service. Communicates directly with the camera over your local network — no cloud, no account, no subscription.

---

## Features

- 📷 **Camera entity** — live snapshot view; RTSP stream for full video and HomeKit via Homebridge
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

> If the feed shows a placeholder, see [Configuring the stream URL](#configuring-the-stream-url) below.

---

## Configuring the Stream URL

The camera streams video locally over RTSP. To enable it:

1. **Settings → Integrations → KodaxHA → Configure**
2. Enter your **RTSP Stream URL** and/or **Snapshot URL**
3. Save — no restart needed

### Finding your RTSP URL

Open **VLC → Media → Open Network Stream** and try these common paths for your camera IP:

```
rtsp://192.168.178.36/
rtsp://192.168.178.36:554/
rtsp://192.168.178.36/live
rtsp://192.168.178.36:554/stream1
```

The first one that shows video is your URL. Once set, the `camera.kodak_camera_live_view` entity becomes a proper live stream that HA can proxy.

### Snapshot URL

For still images (faster refresh in some views):

```
http://192.168.178.36/snapshot.jpg
```

---

## HomeKit via Homebridge

Once the RTSP URL is configured, there are two paths to HomeKit:

### Option A — via Home Assistant (easiest)
Install the **HomeKit Bridge** integration in HA (`Settings → Integrations → HomeKit Bridge`). The `camera.kodak_camera_live_view` entity is exposed to HomeKit automatically alongside all other KodaxHA entities.

### Option B — via homebridge-camera-ffmpeg (direct)
In Homebridge, add a camera source pointed directly at the RTSP URL:

```json
{
  "name": "Kodak Camera",
  "videoConfig": {
    "source": "-i rtsp://192.168.178.36/",
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
| `camera.kodak_camera_live_view` | Camera | Snapshot + RTSP stream |
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

- Camera API reverse-engineered from [kairoaraujo/kodak-smart-home](https://github.com/kairoaraujo/kodak-smart-home)
- Built on top of the original Kodak Smart Home mobile app

## Licence

See [LICENSE](../LICENSE)
