"""Camera platform for KodaxHA — live H264 video via VLVL P2P protocol.

Kodak Smart Home cameras (W101, W121, C525, …) stream video using a proprietary
UDP P2P protocol called VLVL (magic bytes 'VLVL').  This platform:

  1. Resolves the camera's MAC address via get_mac_address.
  2. Starts a minimal asyncio RTSP server bound to localhost.
  3. On each client PLAY request, opens a VLVL session to the camera and
     forwards H264 NALUs as RTP/H264 over TCP.
  4. Returns the RTSP URL from stream_source() so HA's stream integration
     (and Chromecast / frontend) can display the live view.
  5. Provides snapshots by capturing one H264 frame and converting with ffmpeg
     (falls back to the configured snapshot_url if ffmpeg is unavailable).

Architecture:
  ┌──────────────┐  UDP VLVL  ┌────────────────┐  TCP RTSP  ┌──────────────┐
  │ Kodak camera │──────────►│ KodaxRTSPServer │◄──────────│  HA frontend │
  └──────────────┘            └────────────────┘            └──────────────┘
"""
from __future__ import annotations

import asyncio
import logging

import aiohttp
from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CAMERA_IP, CONF_LOCAL_IP, CONF_SNAPSHOT_URL, CONF_STREAM_URL, DOMAIN
from .coordinator import KodaxHACoordinator
from .rtsp_server import KodaxRTSPServer
from .sensor import _device_info
from .vlvl import VLVLFrameReceiver, get_camera_mac, get_local_ip_for, h264_to_jpeg

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KodaxHACoordinator = hass.data[DOMAIN][entry.entry_id]
    camera_ip: str = entry.data[CONF_CAMERA_IP]

    # User-configured URLs take precedence — used as fallback / override
    stream_url: str | None = (
        entry.options.get(CONF_STREAM_URL) or entry.data.get(CONF_STREAM_URL)
    ) or None
    snapshot_url: str | None = (
        entry.options.get(CONF_SNAPSHOT_URL) or entry.data.get(CONF_SNAPSHOT_URL)
    ) or None
    local_ip_override: str | None = (
        entry.options.get(CONF_LOCAL_IP) or entry.data.get(CONF_LOCAL_IP)
    ) or None
    if local_ip_override:
        local_ip_override = local_ip_override.strip() or None

    async_add_entities(
        [KodaxHACamera(coordinator, camera_ip, stream_url, snapshot_url, local_ip_override)]
    )


class KodaxHACamera(CoordinatorEntity[KodaxHACoordinator], Camera):
    """Live-streaming camera entity backed by the VLVL P2P protocol.

    Provides:
      * async_camera_image() — captures one H264 frame and decodes to JPEG
        via ffmpeg (falls back to configured snapshot_url if ffmpeg is absent).
      * stream_source() — returns an RTSP URL served by an in-process server
        that bridges VLVL to RTP/H264/TCP so HA can proxy it via HLS/WebRTC.

    If neither ffmpeg nor a custom snapshot URL is configured the camera entity
    will still load; it simply won't show a thumbnail until one is set.
    """

    _attr_has_entity_name = True
    _attr_name = "Live View"
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(
        self,
        coordinator: KodaxHACoordinator,
        camera_ip: str,
        stream_url: str | None,
        snapshot_url: str | None,
        local_ip_override: str | None = None,
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._camera_ip = camera_ip
        self._override_stream_url = stream_url  # manual override wins
        self._snapshot_url = snapshot_url
        self._attr_unique_id = f"kodaxha_{camera_ip.replace('.', '_')}_camera"
        self._attr_device_info = _device_info(camera_ip)

        self._rtsp_server: KodaxRTSPServer | None = None
        self._mac: str | None = None
        auto_ip = get_local_ip_for(camera_ip)
        self._local_ip: str = local_ip_override or auto_ip
        if local_ip_override:
            _LOGGER.info(
                "KodaxHA (%s): using manual local IP %s (auto-detected: %s)",
                camera_ip, local_ip_override, auto_ip,
            )
        else:
            _LOGGER.debug("KodaxHA (%s): auto-detected local IP %s", camera_ip, auto_ip)
        self._server_started = False

    # ── HA entity lifecycle ─────────────────────────────────────────────────

    async def async_added_to_hass(self) -> None:
        """Start the RTSP bridge server when the entity is added to HA."""
        await super().async_added_to_hass()

        if self._override_stream_url:
            # User has manually configured a stream URL — skip the RTSP server
            _LOGGER.info(
                "KodaxHA (%s): using manually configured stream URL: %s",
                self._camera_ip,
                self._override_stream_url,
            )
            return

        session = async_get_clientsession(self.hass)

        # Resolve MAC address (needed by RTSP server to open VLVL sessions)
        self._mac = await get_camera_mac(self._camera_ip, session)
        if not self._mac:
            _LOGGER.warning(
                "KodaxHA (%s): could not resolve MAC address — live stream unavailable",
                self._camera_ip,
            )
            return

        self._rtsp_server = KodaxRTSPServer(self._camera_ip)
        if await self._rtsp_server.start(session):
            self._server_started = True
            _LOGGER.info(
                "KodaxHA (%s): RTSP server started at %s",
                self._camera_ip,
                self._rtsp_server.rtsp_url,
            )
        else:
            _LOGGER.warning(
                "KodaxHA (%s): RTSP server failed to start — live stream unavailable",
                self._camera_ip,
            )
            self._rtsp_server = None

    async def async_will_remove_from_hass(self) -> None:
        """Shut down the RTSP server when the entity is removed."""
        if self._rtsp_server is not None:
            await self._rtsp_server.stop()
            self._rtsp_server = None
        await super().async_will_remove_from_hass()

    # ── HA Camera interface ─────────────────────────────────────────────────

    async def stream_source(self) -> str | None:
        """Return the RTSP URL for HA stream proxy."""
        # Manual override always wins
        if self._override_stream_url:
            return self._override_stream_url

        # Use built-in RTSP server
        if self._rtsp_server is not None and self._server_started:
            return self._rtsp_server.rtsp_url

        return None

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return a JPEG snapshot.

        Strategy (in order of preference):
          1. Configured snapshot_url (HTTP GET to JPEG).
          2. Capture one VLVL H264 frame and decode with ffmpeg.
        """
        # Option 1: configured HTTP snapshot URL
        if self._snapshot_url:
            session = async_get_clientsession(self.hass)
            try:
                async with asyncio.timeout(10):
                    async with session.get(
                        self._snapshot_url,
                        timeout=aiohttp.ClientTimeout(total=8),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            if data[:2] == b"\xff\xd8":  # valid JPEG
                                return data
            except (aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("Snapshot URL fetch failed: %s", err)

        # Option 2: grab a frame from our own RTSP server (avoids opening a
        # second concurrent VLVL session which the camera rejects).
        if self._rtsp_server is not None and self._server_started:
            rtsp_url = self._rtsp_server.rtsp_url
            if rtsp_url:
                jpeg = await _rtsp_to_jpeg(rtsp_url)
                if jpeg:
                    return jpeg

        # Option 3: open a fresh VLVL session directly (only when RTSP server
        # is not running, e.g. first thumbnail before any stream has started).
        if not self._mac:
            return None

        session = async_get_clientsession(self.hass)
        rx = VLVLFrameReceiver(self._camera_ip, self._local_ip, self._mac)
        try:
            if not await rx.open(session):
                return None
            frame = await rx.receive_one_frame()
        finally:
            rx.close()

        if frame is None:
            return None

        jpeg = await h264_to_jpeg(frame)
        if jpeg:
            return jpeg

        _LOGGER.debug(
            "KodaxHA (%s): ffmpeg unavailable — cannot produce JPEG snapshot. "
            "Install ffmpeg on the HA host to enable thumbnails.",
            self._camera_ip,
        )
        return None


async def _rtsp_to_jpeg(rtsp_url: str) -> bytes | None:
    """Grab one JPEG frame from an RTSP URL using ffmpeg.

    Used to pull a thumbnail from our own local RTSP server without opening
    a second concurrent VLVL session (which the camera rejects).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-rtsp_transport", "tcp",
            "-i", rtsp_url,
            "-frames:v", "1",
            "-vcodec", "mjpeg",
            "-q:v", "2",
            "-f", "image2",
            "pipe:1",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        if stdout and stdout[:2] == b"\xff\xd8":
            return stdout
    except FileNotFoundError:
        pass
    except (asyncio.TimeoutError, OSError) as err:
        _LOGGER.debug("_rtsp_to_jpeg failed: %s", err)
    return None
