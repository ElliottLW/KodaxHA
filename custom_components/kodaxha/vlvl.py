"""VLVL P2P protocol handler for Kodak Smart Home cameras.

Kodak cameras stream H264 video using a proprietary UDP protocol called VLVL
(magic bytes b'VLVL').  When a client requests a session via:

    GET http://<ip>/?req=get_session_key&mode=local&port1=<PORT>&ip=<OUR_IP>&streamname=<MAC>_8

…the camera pushes UDP packets to <OUR_IP>:<PORT>.  Each packet has a 42-byte
VLVL header followed by raw H264 Annex B payload.

Header layout (big-endian):
  0 - 3 : magic  "VLVL" (0x56 0x4C 0x56 0x4C)
  4 - 5 : packet type  (0x000D = video, 0x0020 = control/keepalive)
  6 - 7 : sub-type
  8 -11 : frame timestamp / identifier
 12 -15 : seqS  — absolute packet index of the START of the current frame
 16 -19 : seqC  — absolute packet index of THIS packet
 20 -41 : session data (per-session, not used for decoding)

A new H264 IDR frame begins when seqS == seqC.  All packets with the same
seqS value belong to the same frame.  Reassembling the payloads gives one
complete H264 Annex B IDR access unit.

The camera never sends SPS or PPS NAL units in the stream.  Instead, they are
injected from pre-computed constants below (derived experimentally from slice
header analysis for the W101/W121 at 1280×720 Baseline L3.1 H264).
"""
from __future__ import annotations

import asyncio
import logging
import socket
import struct
import time
from typing import AsyncIterator

import aiohttp

_LOGGER = logging.getLogger(__name__)

# ── H264 codec parameters ──────────────────────────────────────────────────
# SPS for 1280×720 H264 Baseline profile, Level 3.1, CAVLC
# Verified: VLC decodes correctly and reports "1280x720"
_SPS_BODY = bytes(
    [0x67, 0x42, 0xC0, 0x1F, 0xED, 0x00, 0xA0, 0x0B, 0x62]
)
# PPS: Baseline, CAVLC, single slice group, no deblocking ctrl present
_PPS_BODY = bytes([0x68, 0xCE, 0x38, 0x80])

# Annex B framed (with 4-byte start code) — prepended before every IDR frame
_ANNEX_B = b"\x00\x00\x00\x01"
SPS_NALU: bytes = _ANNEX_B + _SPS_BODY   # 13 bytes
PPS_NALU: bytes = _ANNEX_B + _PPS_BODY   # 8  bytes
CODEC_EXTRADATA: bytes = SPS_NALU + PPS_NALU  # 21 bytes

# Base64-encoded SPS/PPS without Annex B start code (for RTSP SDP)
# SPS body b'\x67\x42\xC0\x1F\xED\x00\xA0\x0B\x62' → "Z0LAH+0AoAti"
# PPS body b'\x68\xCE\x38\x80'                       → "aM44gA=="
SPS_B64: str = "Z0LAH+0AoAti"
PPS_B64: str = "aM44gA=="

# ── VLVL protocol constants ────────────────────────────────────────────────
_VLVL_MAGIC = b"VLVL"
_VLVL_HEADER_SIZE = 42
_VLVL_VIDEO_TYPE = 0x000D  # video data packet type

_STREAM_SUFFIX = "_8"        # appended to MAC in get_session_key request
_SESSION_TIMEOUT_S = 5.0     # seconds to wait for each UDP packet
_FRAME_TIMEOUT_S = 10.0      # max seconds to wait for one complete frame
_MAX_PACKETS_PER_FRAME = 300  # safety limit


class VLVLFrameReceiver:
    """Manages a VLVL streaming session and reassembles H264 IDR frames.

    Usage::

        async with aiohttp.ClientSession() as http:
            rx = VLVLFrameReceiver("192.168.1.100", "192.168.1.10", "AABBCCDDEEFF")
            if await rx.open(http):
                frame = await rx.receive_one_frame()  # Annex B bytes w/ SPS+PPS
                rx.close()
    """

    def __init__(self, camera_ip: str, local_ip: str, mac: str) -> None:
        self._camera_ip = camera_ip
        self._local_ip = local_ip
        self._mac = mac.replace(":", "").upper()  # normalise
        self._sock: socket.socket | None = None
        self._port: int = 0

    # ── Public API ──────────────────────────────────────────────────────────

    async def open(self, http_session: aiohttp.ClientSession) -> bool:
        """Open the UDP socket and request a VLVL session from the camera.

        Returns True if the camera accepted the session.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", 0))
        sock.setblocking(False)
        self._port = sock.getsockname()[1]
        self._sock = sock

        url = (
            f"http://{self._camera_ip}/?req=get_session_key"
            f"&mode=local"
            f"&port1={self._port}"
            f"&ip={self._local_ip}"
            f"&streamname={self._mac}{_STREAM_SUFFIX}"
        )
        try:
            async with http_session.get(
                url, timeout=aiohttp.ClientTimeout(total=6)
            ) as resp:
                text = await resp.text()
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("VLVL session request failed: %s", err)
            sock.close()
            self._sock = None
            return False

        if "error=200" not in text:
            _LOGGER.warning("Camera rejected VLVL session: %s", text)
            sock.close()
            self._sock = None
            return False

        _LOGGER.debug(
            "VLVL session opened on UDP port %d (camera %s)",
            self._port,
            self._camera_ip,
        )
        return True

    async def receive_one_frame(self) -> bytes | None:
        """Receive one complete IDR frame.

        Blocks until the first H264 frame is complete (i.e., until the next
        frame begins).  Returns Annex B bytes prefixed with SPS + PPS NALUs,
        or None on timeout / socket error.
        """
        if self._sock is None:
            return None

        loop = asyncio.get_running_loop()
        frame_seq_start: int = -1
        frame_data = bytearray()
        deadline = loop.time() + _FRAME_TIMEOUT_S

        for _ in range(_MAX_PACKETS_PER_FRAME * 2):
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                raw: bytes = await asyncio.wait_for(
                    loop.sock_recv(self._sock, 2048),
                    timeout=min(remaining, _SESSION_TIMEOUT_S),
                )
            except (asyncio.TimeoutError, OSError):
                break

            # --- Parse VLVL header ---
            if len(raw) < _VLVL_HEADER_SIZE:
                continue
            if raw[:4] != _VLVL_MAGIC:
                continue
            pkt_type = struct.unpack_from(">H", raw, 4)[0]
            if pkt_type != _VLVL_VIDEO_TYPE:
                continue  # control/keepalive packet

            seq_s = struct.unpack_from(">I", raw, 12)[0]
            seq_c = struct.unpack_from(">I", raw, 16)[0]
            payload = raw[_VLVL_HEADER_SIZE:]

            new_frame = seq_s == seq_c  # first packet of a new frame

            if new_frame:
                if frame_data:
                    # Previous frame is now complete — return it
                    _LOGGER.debug(
                        "VLVL frame ready: %d bytes (seqS=%d)",
                        len(frame_data),
                        frame_seq_start,
                    )
                    return CODEC_EXTRADATA + bytes(frame_data)
                # Start collecting the first frame
                frame_seq_start = seq_s
                frame_data.extend(payload)
            elif frame_seq_start >= 0 and seq_s == frame_seq_start:
                frame_data.extend(payload)
            # else: packet belongs to a preceding frame we started mid-session

        # Timed out or broke out — return whatever we have
        if frame_data:
            _LOGGER.debug(
                "VLVL frame (timeout): %d bytes", len(frame_data)
            )
            return CODEC_EXTRADATA + bytes(frame_data)
        return None

    async def frame_stream(self) -> AsyncIterator[bytes]:
        """Continuously yield H264 IDR frames (Annex B, SPS+PPS prefixed).

        Runs indefinitely; the caller should cancel the enclosing task to stop.
        If the session dies (no packets for _SESSION_TIMEOUT_S seconds) the
        stream stops automatically.
        """
        if self._sock is None:
            return

        loop = asyncio.get_running_loop()
        frame_seq_start: int = -1
        frame_packets: dict[int, bytes] = {}

        while True:
            try:
                raw: bytes = await asyncio.wait_for(
                    loop.sock_recv(self._sock, 2048),
                    timeout=_SESSION_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                _LOGGER.debug("VLVL stream timeout — stopping")
                break
            except (OSError, asyncio.CancelledError):
                break

            if len(raw) < _VLVL_HEADER_SIZE:
                continue
            if raw[:4] != _VLVL_MAGIC:
                continue
            pkt_type = struct.unpack_from(">H", raw, 4)[0]
            if pkt_type != _VLVL_VIDEO_TYPE:
                continue

            seq_s = struct.unpack_from(">I", raw, 12)[0]
            seq_c = struct.unpack_from(">I", raw, 16)[0]
            payload = raw[_VLVL_HEADER_SIZE:]

            if seq_s == seq_c:  # new frame starting
                if frame_packets:  # yield previous frame (sorted by seqC)
                    assembled = bytearray()
                    for _, pkt_payload in sorted(frame_packets.items()):
                        assembled.extend(pkt_payload)
                    yield CODEC_EXTRADATA + bytes(assembled)
                frame_seq_start = seq_s
                frame_packets: dict[int, bytes] = {seq_c: payload}
            elif frame_seq_start >= 0 and seq_s == frame_seq_start:
                frame_packets[seq_c] = payload

    def close(self) -> None:
        """Close the UDP socket and release resources."""
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
            _LOGGER.debug("VLVL session closed (was on port %d)", self._port)


# ── Utilities ──────────────────────────────────────────────────────────────


async def get_camera_mac(
    camera_ip: str,
    http_session: aiohttp.ClientSession,
) -> str | None:
    """Return the camera's MAC address (e.g. 'AABBCCDDEEFF')."""
    url = f"http://{camera_ip}/?req=get_mac_address"
    try:
        async with http_session.get(
            url, timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            text = (await resp.text()).strip()
            # Response: "get_mac_address: AABBCCDDEEFF"
            if ": " in text:
                mac = text.split(": ", 1)[1].strip()
            else:
                mac = text
            mac = mac.replace(":", "").replace("-", "").upper()
            if len(mac) == 12 and all(c in "0123456789ABCDEF" for c in mac):
                return mac
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("get_mac_address failed: %s", err)
    return None


def get_local_ip_for(camera_ip: str) -> str:
    """Return the local IP that the OS would use to reach camera_ip.

    This creates a dummy UDP socket (no packets sent) to determine
    which local interface the OS would route the traffic through.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((camera_ip, 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "0.0.0.0"


async def h264_to_jpeg(h264_bytes: bytes) -> bytes | None:
    """Decode an H264 Annex B frame to JPEG using ffmpeg.

    Returns JPEG bytes or None if ffmpeg is unavailable / decoding fails.
    The h264_bytes should start with SPS+PPS NALUs (CODEC_EXTRADATA) for
    reliable decoding.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "h264",  # raw H264 Annex B input
            "-i",
            "pipe:0",
            "-frames:v",
            "1",       # decode only one frame
            "-vcodec",
            "mjpeg",
            "-q:v",
            "2",       # JPEG quality (1=best, 31=worst)
            "-f",
            "image2",
            "pipe:1",  # output to stdout
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(
            proc.communicate(h264_bytes), timeout=10.0
        )
        if stdout and stdout[:2] == b"\xff\xd8":  # JPEG SOI magic
            return stdout
        _LOGGER.debug("ffmpeg output is not JPEG (len=%d)", len(stdout) if stdout else 0)
    except FileNotFoundError:
        _LOGGER.warning(
            "ffmpeg not found — cannot decode H264 frames to JPEG. "
            "Install ffmpeg on the host to enable live snapshots."
        )
    except (asyncio.TimeoutError, OSError) as err:
        _LOGGER.debug("h264_to_jpeg failed: %s", err)
    return None
