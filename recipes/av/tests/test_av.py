import io


def _solid_video_frame(av, width, height, luma):
    """A yuv420p frame with every plane filled to a constant."""
    frame = av.VideoFrame(width, height, "yuv420p")
    for index, plane in enumerate(frame.planes):
        plane.update(bytes([luma if index == 0 else 128]) * plane.buffer_size)
    return frame


def _sine_audio_frame(av, samples, sample_rate):
    """A mono s16 frame holding a low-amplitude triangle wave."""
    frame = av.AudioFrame(format="s16", layout="mono", samples=samples)
    payload = bytearray()
    for n in range(samples):
        value = (n % 64) * 256 - 8192
        payload += int(value).to_bytes(2, "little", signed=True)
    frame.planes[0].update(bytes(payload))
    frame.sample_rate = sample_rate
    return frame


def test_import_and_library_versions():
    """The package imports, which means all seven flet-libffmpeg libraries
    loaded and every extension module bound to them."""
    import av

    for name in (
        "libavutil",
        "libavcodec",
        "libavformat",
        "libavdevice",
        "libavfilter",
        "libswscale",
        "libswresample",
    ):
        assert name in av.library_versions, name
        assert av.library_versions[name][0] > 0, name

    assert av.ffmpeg_version_info


def test_build_is_lgpl_only():
    """flet-libffmpeg is configured without --enable-gpl / --enable-nonfree, so
    every library reports an LGPL licence and no GPL-only codec is linked.
    Turning either on flips this, and the wheel's declared LGPL-2.1-or-later
    metadata would stop describing what it actually contains."""
    from av._core import library_meta
    from av.codec.codec import codecs_available

    for name, meta in library_meta.items():
        assert meta["license"].startswith("LGPL"), (name, meta["license"])

    for name in ("libx264", "libx265", "libxvid", "libfdk_aac"):
        assert name not in codecs_available, name


def test_expected_codecs_available():
    """The codecs a Flet app is most likely to reach for are compiled in. These
    are FFmpeg's own native implementations — no external codec libraries are
    linked, so the set is fixed by the recipe rather than by the host."""
    from av.codec.codec import Codec

    for name in ("h264", "hevc", "vp8", "vp9", "aac", "mp3", "opus", "flac"):
        assert Codec(name, "r").name == name, name

    for name in ("mpeg4", "mjpeg", "aac", "flac"):
        assert Codec(name, "w").name == name, name


def test_container_formats_available():
    """libavformat carries the common container muxers/demuxers."""
    import av

    for name in ("mp4", "mov", "matroska", "webm", "wav", "mp3"):
        assert name in av.formats_available, name


def test_video_encode_decode_roundtrip():
    """Encode synthetic frames into an in-memory MP4 and read them back.
    Exercises the muxer, the encoder, the file-like I/O path (av.open on a
    BytesIO — the documented way to play a network stream on mobile) and the
    decoder in one pass."""
    import av

    width, height, count = 160, 120, 10

    buffer = io.BytesIO()
    with av.open(buffer, mode="w", format="mp4") as container:
        stream = container.add_stream("mpeg4", rate=25)
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"
        for index in range(count):
            frame = _solid_video_frame(av, width, height, 16 + index * 8)
            container.mux(stream.encode(frame))
        container.mux(stream.encode(None))

    assert buffer.tell() > 0
    buffer.seek(0)

    decoded = []
    with av.open(buffer) as container:
        stream = container.streams.video[0]
        assert stream.codec_context.name == "mpeg4"
        for frame in container.decode(stream):
            decoded.append(frame)

    assert len(decoded) == count
    assert decoded[0].width == width
    assert decoded[0].height == height
    assert decoded[0].format.name == "yuv420p"


def test_audio_encode_decode_roundtrip():
    """Encode PCM to AAC in an in-memory MP4 and decode it back. FFmpeg's own
    AAC encoder — no libfdk_aac (nonfree) in this build."""
    import av

    sample_rate = 44100

    buffer = io.BytesIO()
    with av.open(buffer, mode="w", format="mp4") as container:
        stream = container.add_stream("aac", rate=sample_rate)
        resampler = av.AudioResampler(
            format=stream.format, layout=stream.layout, rate=sample_rate
        )
        for _ in range(8):
            frame = _sine_audio_frame(av, 1024, sample_rate)
            for resampled in resampler.resample(frame):
                container.mux(stream.encode(resampled))
        for resampled in resampler.resample(None):
            container.mux(stream.encode(resampled))
        container.mux(stream.encode(None))

    buffer.seek(0)

    total_samples = 0
    with av.open(buffer) as container:
        stream = container.streams.audio[0]
        assert stream.codec_context.name == "aac"
        assert stream.codec_context.sample_rate == sample_rate
        for frame in container.decode(stream):
            total_samples += frame.samples

    assert total_samples > 0


def test_video_reformat_uses_swscale():
    """VideoFrame.reformat is libswscale: convert pixel format and scale."""
    import av

    frame = _solid_video_frame(av, 64, 48, 200)
    converted = frame.reformat(format="rgb24")
    assert converted.format.name == "rgb24"

    scaled = frame.reformat(width=32, height=24, format="yuv420p")
    assert (scaled.width, scaled.height) == (32, 24)


def test_audio_resampler_uses_swresample():
    """AudioResampler is libswresample: rate + format conversion."""
    import av

    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    frame = _sine_audio_frame(av, 1024, 44100)

    out = resampler.resample(frame) + resampler.resample(None)
    resampled_samples = sum(f.samples for f in out)

    assert resampled_samples > 0
    assert all(f.sample_rate == 16000 for f in out)


def test_filter_graph_uses_avfilter():
    """A buffer -> vflip -> buffersink graph exercises libavfilter end to end."""
    from fractions import Fraction

    import av

    graph = av.filter.Graph()
    source = graph.add_buffer(
        width=64, height=48, format="yuv420p", time_base=Fraction(1, 25)
    )
    flip = graph.add("vflip")
    sink = graph.add("buffersink")
    source.link_to(flip)
    flip.link_to(sink)
    graph.configure()

    graph.push(_solid_video_frame(av, 64, 48, 90))
    out = graph.pull()

    assert (out.width, out.height) == (64, 48)


def test_bitstream_filters_available():
    """libavcodec's bitstream filters are compiled in — h264_mp4toannexb is the
    one anything feeding a platform decoder needs. Instantiate the parameterless
    `null` filter rather than that one, which errors without H.264 codec
    parameters to work from."""
    import av

    assert "h264_mp4toannexb" in av.bitstream_filters_available
    assert av.BitStreamFilterContext("null") is not None


def test_no_capture_devices_registered():
    """flet-libffmpeg is built --disable-devices: libavdevice is linked (PyAV
    calls avdevice_register_all at import) but registers nothing, so there is no
    camera, microphone or `lavfi` source to open. Pinned so that enabling
    devices later surfaces as a test change rather than a surprise, and so the
    README's account of what this wheel can and cannot do stays honest."""
    import av
    import pytest

    for name in ("avfoundation", "android_camera", "v4l2", "lavfi"):
        assert name not in av.formats_available, name
        with pytest.raises(ValueError):
            av.enumerate_input_devices(name)


def test_no_tls_protocols():
    """flet-libffmpeg links no TLS backend, so FFmpeg has no `https` protocol —
    the reason the README tells consumers to fetch bytes themselves and hand
    `av.open` a file-like object. Resolved before any socket is opened, so this
    makes no network request."""
    import av
    import pytest

    with pytest.raises(av.error.ProtocolNotFoundError):
        av.open("https://example.invalid/clip.mp4")
