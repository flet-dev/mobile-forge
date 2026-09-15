"""Writes a short MP4 with a video and an audio stream, reads it back to describe
what actually landed in the file, and pulls stills out of it as JPEG bytes an
`ft.Image` can display.
"""

import io
import math
import os
import time
from fractions import Fraction

import av

WIDTH, HEIGHT = 320, 240
FPS = 24
SECONDS = 3
SAMPLE_RATE = 44100
TONE_HZ = 440


def library_versions() -> str:
    """One line naming the FFmpeg build the wheel is linked against."""
    major, minor, micro = av.library_versions["libavcodec"]
    return f"PyAV {av.__version__} · FFmpeg {av.ffmpeg_version_info} · libavcodec {major}.{minor}.{micro}"


def clip_path() -> str:
    """Where the clip lives: app-private storage that survives a restart."""
    return os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "clip.mp4")


def _video_frame(index: int):
    """A yuv420p frame with a gradient background and a bar sweeping across it.

    Planes are filled a row at a time because a plane's `line_size` can exceed
    the picture width — FFmpeg pads each row for alignment, and `update()` wants
    exactly `buffer_size` bytes.
    """
    frame = av.VideoFrame(WIDTH, HEIGHT, "yuv420p")

    bar = int((index / (FPS * SECONDS)) * WIDTH)
    luma = bytearray(16 + (x * 180 // WIDTH) for x in range(WIDTH))
    for x in range(bar, min(bar + 24, WIDTH)):
        luma[x] = 235

    for plane_index, plane in enumerate(frame.planes):
        rows = plane.buffer_size // plane.line_size
        if plane_index == 0:
            row = bytes(luma) + b"\x00" * (plane.line_size - WIDTH)
        else:
            # Chroma: a constant tint that drifts over the clip, so the frames
            # are visibly different from one another and not just brighter.
            value = 90 + (index * 3) % 80
            row = bytes([value]) * plane.line_size
        plane.update(row * rows)

    return frame


def _audio_frames(stream):
    """A 440 Hz tone, resampled into whatever layout the AAC encoder asked for."""
    resampler = av.AudioResampler(
        format=stream.format, layout=stream.layout, rate=SAMPLE_RATE
    )
    block = 1024
    for start in range(0, SAMPLE_RATE * SECONDS, block):
        frame = av.AudioFrame(format="s16", layout="mono", samples=block)
        payload = bytearray()
        for n in range(block):
            value = int(
                8000 * math.sin(2 * math.pi * TONE_HZ * (start + n) / SAMPLE_RATE)
            )
            payload += value.to_bytes(2, "little", signed=True)
        frame.planes[0].update(bytes(payload))
        frame.sample_rate = SAMPLE_RATE
        yield from resampler.resample(frame)
    yield from resampler.resample(None)


def write_clip(path: str) -> float:
    """Mux a synthetic video + audio clip to `path`; return the seconds it took.

    mpeg4 rather than h264: this wheel's FFmpeg is LGPL, so it carries no x264
    and has no H.264 encoder at all. AAC is FFmpeg's own encoder.
    """
    started = time.monotonic()

    with av.open(path, mode="w") as container:
        video = container.add_stream("mpeg4", rate=FPS)
        video.width, video.height = WIDTH, HEIGHT
        video.pix_fmt = "yuv420p"
        audio = container.add_stream("aac", rate=SAMPLE_RATE)

        for index in range(FPS * SECONDS):
            container.mux(video.encode(_video_frame(index)))
        for frame in _audio_frames(audio):
            container.mux(audio.encode(frame))

        container.mux(video.encode(None))
        container.mux(audio.encode(None))

    return time.monotonic() - started


def probe(path: str) -> list[tuple[str, str]]:
    """Describe the file as label/value pairs, read back off the container."""
    with av.open(path) as container:
        rows = [
            ("container", container.format.long_name),
            ("size", f"{os.path.getsize(path) / 1000:.0f} KB"),
            ("duration", f"{container.duration / av.time_base:.2f} s"),
        ]
        for stream in container.streams.video:
            rows.append(
                (
                    "video",
                    f"{stream.codec_context.name} · {stream.width}×{stream.height}"
                    f" · {float(stream.average_rate):.0f} fps",
                )
            )
        for stream in container.streams.audio:
            rows.append(
                (
                    "audio",
                    f"{stream.codec_context.name} · {stream.codec_context.sample_rate} Hz"
                    f" · {stream.codec_context.layout.name}",
                )
            )
    return rows


def _jpeg(frame, width: int) -> bytes:
    """Re-encode one decoded frame as a JPEG, scaled to `width`."""
    height = width * frame.height // frame.width
    scaled = frame.reformat(width=width, height=height, format="yuvj420p")

    buffer = io.BytesIO()
    with av.open(buffer, mode="w", format="mjpeg") as container:
        stream = container.add_stream("mjpeg", rate=1)
        stream.width, stream.height = width, height
        stream.pix_fmt = "yuvj420p"
        stream.time_base = Fraction(1, 1)
        container.mux(stream.encode(scaled))
        container.mux(stream.encode(None))
    return buffer.getvalue()


def thumbnails(path: str, count: int = 4, width: int = 140) -> list[tuple[str, bytes]]:
    """Seek to `count` evenly spaced points and return (timestamp, JPEG) pairs."""
    stills = []
    with av.open(path) as container:
        stream = container.streams.video[0]
        span = container.duration / av.time_base

        for index in range(count):
            seconds = span * index / count
            container.seek(int(seconds * av.time_base))
            for frame in container.decode(stream):
                stills.append((f"{float(frame.time):.2f}s", _jpeg(frame, width)))
                break
    return stills
