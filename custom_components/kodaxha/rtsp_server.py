"""Minimal async RTSP/RTP server for KodaxHA.

This module implements a self-contained asyncio RTSP server that bridges the
Kodak VLVL P2P UDP stream into a standard RTSP connection that Home Assistant's
stream integration (and other RTSP-capable clients) can consume.

Architecture:
  ┌──────────────┐  UDP VLVL  ┌──────────────────┐  TCP RTSP  ┌────────────┐
  │ Kodak camera │──────────►│  VLVLFrameReceiver│◄──────────►│  HA stream │
  └──────────────┘            └──────────────────┘            └────────────┘

The server listens on an OS-assigned TCP port (loopback only). One VLVL
session feeds every connected client, and it only runs while someone is
watching: it starts on the first PLAY and stops _IDLE_STOP_S after the last
client leaves (the camera is battery powered, and streaming costs power and
Wi-Fi airtime).

Protocol notes:
  • RTSP is implemented as a subset: OPTIONS / DESCRIBE / SETUP / PLAY / TEARDOWN
  • Video is delivered as RTP H264 RFC 6184 over TCP (interleaved, RFC 2326 §10.12)
  • NALUs larger than _RTP_MAX_PAYLOAD_BYTES are fragmented with FU-A (RFC 6184 §5.8)
  • RTP timestamps come from the camera's capture times, so players can smooth
    out the bursts the camera's Wi-Fi delivers frames in
  • The camera's audio (G.722, 16 kHz) is not offered yet
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import socket
import struct
import time
from typing import Any, Callable

from .vlvl import (
    CODEC_EXTRADATA,
    PPS_B64,
    PROFILE_LEVEL_ID,
    SPS_B64,
    VLVLFrameReceiver,
    get_camera_mac,
    is_keyframe,
    get_local_ip_for,
)

_LOGGER = logging.getLogger(__name__)

_RTP_MAX_PAYLOAD_BYTES = 1400  # stay safely below typical MTU
_RTSP_SERVER_BIND_IP = "127.0.0.1"  # loopback only — HA accesses via localhost
_MAX_CLIENTS_QUEUED = 2
_IDLE_STOP_S = 30.0  # keep streaming this long after the last viewer leaves

# ── RTP helpers ────────────────────────────────────────────────────────────

def _build_rtp_packet(
    payload: bytes,
    ssrc: int,
    seq: int,
    timestamp: int,
    marker: bool = False,
) -> bytes:
    """Build a single RTP packet (RFC 3550 header + payload)."""
    flags = 0b10_0_0_0000  # version=2, no padding, no extension, CC=0
    marker_pt = (0x80 if marker else 0x00) | 96  # PT=96 (dynamic H264)
    header = struct.pack(
        "!BBHII",
        flags,
        marker_pt,
        seq & 0xFFFF,
        timestamp & 0xFFFFFFFF,
        ssrc & 0xFFFFFFFF,
    )
    return header + payload


def _rtp_interleave(channel: int, rtp: bytes) -> bytes:
    """Wrap an RTP packet in RTSP TCP interleaving framing (RFC 2326 §10.12)."""
    return struct.pack("!BBH", 0x24, channel, len(rtp)) + rtp


def _nalu_packets(nalu: bytes, ssrc: int, seq: int, ts: int) -> list[bytes]:
    """Convert one NALU into a list of RTP packets (single-NAL or FU-A).

    Returns a list of interleaved RTSP/RTP byte strings ready to write on
    the TCP socket.
    """
    result: list[bytes] = []

    # Strip any leading Annex B start code (3-byte or 4-byte)
    if nalu[:4] == b"\x00\x00\x00\x01":
        nalu = nalu[4:]
    elif nalu[:3] == b"\x00\x00\x01":
        nalu = nalu[3:]

    if not nalu:
        return result

    max_payload = _RTP_MAX_PAYLOAD_BYTES

    if len(nalu) <= max_payload:
        # Single NAL unit packet
        pkt = _build_rtp_packet(nalu, ssrc, seq, ts, marker=True)
        result.append(_rtp_interleave(0, pkt))
    else:
        # FU-A fragmentation
        nal_header = nalu[0]
        nal_body = nalu[1:]
        chunks = [
            nal_body[i : i + max_payload - 2]
            for i in range(0, len(nal_body), max_payload - 2)
        ]
        for i, chunk in enumerate(chunks):
            start = 0x80 if i == 0 else 0x00
            end = 0x40 if i == len(chunks) - 1 else 0x00
            fu_indicator = (nal_header & 0xE0) | 28  # FU-A indicator
            fu_header = start | end | (nal_header & 0x1F)
            payload = bytes([fu_indicator, fu_header]) + chunk
            marker = i == len(chunks) - 1
            pkt = _build_rtp_packet(payload, ssrc, seq + i, ts, marker=marker)
            result.append(_rtp_interleave(0, pkt))
        seq += len(chunks) - 1  # caller must handle seq advance

    return result


def _split_nalus(annex_b: bytes) -> list[bytes]:
    """Split Annex B H264 stream into individual NALUs (without start codes).

    Uses O(n) boundary detection and byte-slice extraction rather than
    byte-by-byte concatenation, so large IDR frames don't cause quadratic
    allocation overhead.
    """
    # Collect (position, start_code_length) for every start code
    positions: list[tuple[int, int]] = []
    i = 0
    n = len(annex_b)
    while i < n - 2:
        if annex_b[i : i + 4] == b"\x00\x00\x00\x01":
            positions.append((i, 4))
            i += 4
        elif annex_b[i : i + 3] == b"\x00\x00\x01":
            positions.append((i, 3))
            i += 3
        else:
            i += 1
    nalus: list[bytes] = []
    for j, (pos, sc_len) in enumerate(positions):
        start = pos + sc_len
        end = positions[j + 1][0] if j + 1 < len(positions) else n
        nalu = annex_b[start:end]
        if nalu:
            nalus.append(nalu)
    return nalus


# ── RTSP session handler ────────────────────────────────────────────────────

class _RTSPClientHandler:
    """Handles a single RTSP TCP connection end-to-end."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        camera_ip: str,
        mac: str,
        local_ip: str,
        server_port: int = 0,
        subscribe: Callable[[asyncio.Queue], None] | None = None,
        unsubscribe: Callable[[asyncio.Queue], None] | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._camera_ip = camera_ip
        self._mac = mac
        self._local_ip = local_ip
        self._server_port = server_port
        self._subscribe = subscribe or (lambda q: None)
        self._unsubscribe = unsubscribe or (lambda q: None)
        self._session_id = f"{random.randint(0, 0xFFFFFFFF):08X}"
        self._ssrc = random.randint(0, 0xFFFFFFFF)
        self._rtp_seq: int = random.randint(0, 0xFFFF)
        self._rtp_ts: int = random.randint(0, 0xFFFFFFFF)

    # -- RTSP request dispatcher ----------------------------------------

    async def run(self, http_session: Any) -> None:  # noqa: ANN001
        """Read and respond to RTSP requests until the connection closes."""
        try:
            while True:
                line = await asyncio.wait_for(
                    self._reader.readline(), timeout=30.0
                )
                if not line:
                    break
                line = line.decode(errors="replace").strip()
                if not line:
                    continue

                parts = line.split()
                if len(parts) < 2:
                    continue
                method = parts[0]
                # Read headers until blank line
                headers: dict[str, str] = {}
                while True:
                    hline = await asyncio.wait_for(
                        self._reader.readline(), timeout=5.0
                    )
                    hline = hline.decode(errors="replace").strip()
                    if not hline:
                        break
                    if ": " in hline:
                        k, _, v = hline.partition(": ")
                        headers[k.upper()] = v.strip()

                cseq = headers.get("CSEQ", "0")
                _LOGGER.debug("RTSP %s CSeq=%s", method, cseq)

                if method == "OPTIONS":
                    await self._send_response(
                        cseq,
                        "200 OK",
                        {"Public": "OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN"},
                    )
                elif method == "DESCRIBE":
                    await self._handle_describe(cseq)
                elif method == "SETUP":
                    await self._handle_setup(cseq, headers)
                elif method == "PLAY":
                    await self._handle_play(cseq, http_session)
                elif method == "TEARDOWN":
                    await self._send_response(cseq, "200 OK")
                    break
                else:
                    await self._send_response(cseq, "501 Not Implemented")

        except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self._writer.close()

    async def _handle_describe(self, cseq: str) -> None:
        base = f"rtsp://{_RTSP_SERVER_BIND_IP}:{self._server_port}/"
        sdp = (
            "v=0\r\n"
            f"o=- 0 0 IN IP4 {_RTSP_SERVER_BIND_IP}\r\n"
            "s=KodaxHA Camera\r\n"
            f"c=IN IP4 {_RTSP_SERVER_BIND_IP}\r\n"
            "t=0 0\r\n"
            "m=video 0 RTP/AVP 96\r\n"
            "a=control:trackID=0\r\n"
            "a=rtpmap:96 H264/90000\r\n"
            f"a=fmtp:96 packetization-mode=1;profile-level-id={PROFILE_LEVEL_ID};"
            f"sprop-parameter-sets={SPS_B64},{PPS_B64}\r\n"
        )
        body = sdp.encode()
        await self._send_response(
            cseq,
            "200 OK",
            {
                "Content-Type": "application/sdp",
                "Content-Base": base,
            },
            body,
        )

    async def _handle_setup(self, cseq: str, headers: dict[str, str]) -> None:
        await self._send_response(
            cseq,
            "200 OK",
            {
                "Transport": "RTP/AVP/TCP;unicast;interleaved=0-1",
                "Session": self._session_id,
            },
        )

    async def _handle_play(self, cseq: str, http_session: Any) -> None:  # noqa: ANN001
        await self._send_response(
            cseq,
            "200 OK",
            {
                "Session": self._session_id,
                "Range": "npt=0.000-",
                "RTP-Info": f"url=rtsp://{_RTSP_SERVER_BIND_IP}:{self._server_port}/trackID=0;"
                            f"seq={self._rtp_seq};rtptime={self._rtp_ts}",
            },
        )
        # Subscribe to the server's continuous broadcaster.
        # Items are (frame, camera capture ms); None signals the stream ended.
        frame_q: asyncio.Queue[tuple[bytes, int] | None] = asyncio.Queue(maxsize=30)
        self._subscribe(frame_q)  # starts the camera stream if it isn't running
        start_ts = self._rtp_ts
        base_ms: int | None = None
        last_ms = 0
        waiting_for_key = True
        try:
            while True:
                try:
                    item = await asyncio.wait_for(frame_q.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    break
                if item is None:
                    break
                frame, capture_ms = item
                if waiting_for_key:
                    if not is_keyframe(frame):
                        continue  # P-frames are useless until the first keyframe
                    waiting_for_key = False
                # Stamp with the camera's capture time, not arrival time: the
                # camera's Wi-Fi delivers frames in bursts, and capture times
                # let the player show them evenly.
                if base_ms is None or not 0 <= capture_ms - last_ms < 5000:
                    # first frame, or the camera clock jumped (new session)
                    start_ts, base_ms = (self._rtp_ts + 6000) & 0xFFFFFFFF, capture_ms
                last_ms = capture_ms
                self._rtp_ts = (start_ts + (capture_ms - base_ms) * 90) & 0xFFFFFFFF
                nalus = _split_nalus(frame)
                for nalu in nalus:
                    pkts = _nalu_packets(nalu, self._ssrc, self._rtp_seq, self._rtp_ts)
                    self._rtp_seq = (self._rtp_seq + len(pkts)) & 0xFFFF
                    for pkt in pkts:
                        self._writer.write(pkt)
                await self._writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        finally:
            self._unsubscribe(frame_q)

    # -- RTSP response builder ------------------------------------------

    async def _send_response(
        self,
        cseq: str,
        status: str,
        extra_headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> None:
        lines = [
            f"RTSP/1.0 {status}",
            f"CSeq: {cseq}",
            "Server: KodaxHA/1.0",
        ]
        if extra_headers:
            for k, v in extra_headers.items():
                lines.append(f"{k}: {v}")
        # Add Content-Length only if not already supplied in extra_headers
        if body and (
            not extra_headers or "Content-Length" not in {k.title() for k in extra_headers}
        ):
            lines.append(f"Content-Length: {len(body)}")
        lines.append("")  # blank line
        lines.append("")
        response = "\r\n".join(lines).encode()
        self._writer.write(response)
        if body:
            self._writer.write(body)
        await self._writer.drain()


# ── Public server class ────────────────────────────────────────────────────

class KodaxRTSPServer:
    """Async RTSP server bound to loopback; bridges VLVL → RTSP for one camera.

    Lifecycle:
        server = KodaxRTSPServer(camera_ip="192.168.1.100")
        await server.start(http_session)         # binds port, starts serving
        rtsp_url = server.rtsp_url               # e.g. "rtsp://127.0.0.1:PORT/"
        await server.stop()                      # shuts down cleanly
    """

    def __init__(self, camera_ip: str) -> None:
        self._camera_ip = camera_ip
        self._mac: str | None = None
        self._local_ip: str = get_local_ip_for(camera_ip)
        self._server: asyncio.AbstractServer | None = None
        self._port: int = 0
        self._http_session: Any = None
        # Fan-out broadcaster: one VLVL session feeds all connected RTSP
        # clients.  Each client owns one asyncio.Queue in _client_queues; the
        # _stream_loop task (running only while there are clients) broadcasts
        # every received frame to all of them.
        self._client_queues: list[asyncio.Queue] = []
        self._resync: set[asyncio.Queue] = set()  # slow clients waiting for a keyframe
        self._stream_task: asyncio.Task | None = None
        self._idle_timer: asyncio.TimerHandle | None = None
        # Most recent keyframe while streaming, for thumbnails without opening
        # a competing VLVL session.
        self._last_frame: bytes | None = None
        self._last_frame_at = 0.0

    @property
    def rtsp_url(self) -> str | None:
        """Return the RTSP URL clients should use, or None if not started."""
        if self._port:
            return f"rtsp://{_RTSP_SERVER_BIND_IP}:{self._port}/"
        return None

    @property
    def is_streaming(self) -> bool:
        """True while the camera stream is running (someone is watching)."""
        return self._stream_task is not None and not self._stream_task.done()

    def get_last_frame(self) -> bytes | None:
        """Return the latest keyframe while streaming, or None.

        Used by async_camera_image to produce JPEG thumbnails without opening
        a competing VLVL session.  Frames older than a few seconds (stream
        stalled or stopped) are not returned.
        """
        if self.is_streaming and time.monotonic() - self._last_frame_at < 5:
            return self._last_frame
        return None

    # -- on-demand streaming -------------------------------------------

    def _add_client(self, queue: asyncio.Queue) -> None:
        self._client_queues.append(queue)
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
        if not self.is_streaming:
            _LOGGER.debug("KodaxRTSPServer: viewer connected, starting camera stream")
            self._stream_task = asyncio.ensure_future(self._stream_loop())

    def _remove_client(self, queue: asyncio.Queue) -> None:
        if queue in self._client_queues:
            self._client_queues.remove(queue)
        self._resync.discard(queue)
        if not self._client_queues and self._idle_timer is None and self.is_streaming:
            # Linger briefly: HA's stream worker often reconnects straight away.
            self._idle_timer = asyncio.get_running_loop().call_later(
                _IDLE_STOP_S, self._stop_if_idle
            )

    def _stop_if_idle(self) -> None:
        self._idle_timer = None
        if not self._client_queues and self._stream_task is not None:
            _LOGGER.debug("KodaxRTSPServer: no viewers, stopping camera stream")
            self._stream_task.cancel()
            self._stream_task = None

    async def start(self, http_session: Any) -> bool:  # noqa: ANN001
        """Bind the RTSP port and start accepting clients.

        Returns True if the server started successfully.
        """
        self._http_session = http_session

        # Resolve MAC address
        self._mac = await get_camera_mac(self._camera_ip, http_session)
        if not self._mac:
            _LOGGER.error(
                "KodaxRTSPServer: could not resolve MAC address for %s",
                self._camera_ip,
            )
            return False

        try:
            self._server = await asyncio.start_server(
                self._handle_client,
                _RTSP_SERVER_BIND_IP,
                0,  # OS picks a free port
                limit=64 * 1024,
                backlog=_MAX_CLIENTS_QUEUED,
            )
        except OSError as err:
            _LOGGER.error("KodaxRTSPServer: failed to bind: %s", err)
            return False

        # Retrieve the assigned port
        sockets = self._server.sockets
        if sockets:
            self._port = sockets[0].getsockname()[1]

        _LOGGER.info(
            "KodaxRTSPServer started on %s:%d for camera %s (MAC %s)",
            _RTSP_SERVER_BIND_IP,
            self._port,
            self._camera_ip,
            self._mac,
        )
        # The camera stream itself starts when the first client sends PLAY.
        return True

    async def stop(self) -> None:
        """Cancel the broadcaster task, drain client queues, and close."""
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
        if self._stream_task is not None:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
            self._stream_task = None
        # Signal any waiting RTSP clients that the stream has ended.
        for q in list(self._client_queues):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
        self._client_queues.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            self._port = 0
            _LOGGER.debug("KodaxRTSPServer stopped for %s", self._camera_ip)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Dispatch each incoming RTSP connection to a handler coroutine."""
        peer = writer.get_extra_info("peername")
        _LOGGER.debug("RTSP client connected from %s", peer)
        handler = _RTSPClientHandler(
            reader,
            writer,
            self._camera_ip,
            self._mac,  # type: ignore[arg-type]
            self._local_ip,
            self._port,
            subscribe=self._add_client,
            unsubscribe=self._remove_client,
        )
        await handler.run(self._http_session)
        _LOGGER.debug("RTSP client disconnected from %s", peer)

    async def _stream_loop(self) -> None:
        """Receive VLVL frames and broadcast them to all subscribers.

        Opens a single VLVL session and fans every frame out to all
        per-client asyncio.Queue instances in self._client_queues.  When the
        session ends (timeout or error) it waits briefly then reopens.  Runs
        while there are viewers; cancelled by _stop_if_idle() or stop().
        """
        _RECONNECT_DELAY_S = 2.0

        while True:
            rx = VLVLFrameReceiver(
                self._camera_ip,
                self._local_ip,
                self._mac,  # type: ignore[arg-type]
            )
            try:
                opened = await rx.open(self._http_session)
            except asyncio.CancelledError:
                rx.close()
                return
            if not opened:
                try:
                    await asyncio.sleep(_RECONNECT_DELAY_S)
                except asyncio.CancelledError:
                    return
                continue

            try:
                async for frame, capture_ms in rx.frame_stream(with_timestamps=True):
                    key = is_keyframe(frame)
                    if key:
                        self._last_frame = frame  # thumbnails need a keyframe
                        self._last_frame_at = time.monotonic()
                    for q in list(self._client_queues):
                        if q in self._resync:
                            if not key:
                                continue
                            self._resync.discard(q)
                        try:
                            q.put_nowait((frame, capture_ms))
                        except asyncio.QueueFull:
                            # A slow client can't skip a P-frame without
                            # smearing: drop its backlog and restart it at the
                            # next keyframe instead.
                            while not q.empty():
                                q.get_nowait()
                            if key:
                                q.put_nowait((frame, capture_ms))
                            else:
                                self._resync.add(q)
            except asyncio.CancelledError:
                rx.close()
                return  # server shutting down
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug("VLVL broadcaster error: %s", exc)
            finally:
                rx.close()

            # Brief cooldown before reconnecting.
            try:
                await asyncio.sleep(_RECONNECT_DELAY_S)
            except asyncio.CancelledError:
                return
