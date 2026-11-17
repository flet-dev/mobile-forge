# sherpa-onnx

[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) is an offline speech toolkit from the
k2-fsa (next-gen Kaldi) project: speech-to-text (streaming and whole-file), text-to-speech,
voice activity detection, keyword spotting, speaker identification and more, all running on
[ONNX Runtime](https://onnxruntime.ai/). In a Flet app it turns speech into text, or text
into speech, on the device, with no server and no network once a model is downloaded.

This wheel compiles sherpa-onnx's C++ core for Android and iOS, together with ONNX Runtime.
It is self-contained: it does not need the `onnxruntime` package, nor PyPI's
`sherpa-onnx-core`.

## Install

```toml
dependencies = [
    "flet",
    "sherpa-onnx==2.0.1",
]
```

numpy is not required. sherpa-onnx accepts plain lists of float samples, and imports numpy
only inside the few helpers that need it.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`transcribe`](examples/transcribe) — downloads a 29 MB English model on first run, then
  transcribes a recording offline.

## Usage in a Flet app

Every feature needs a model, and models are separate downloads, published as `.tar.bz2`
archives on sherpa-onnx's GitHub releases
([speech-to-text](https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models),
[text-to-speech](https://github.com/k2-fsa/sherpa-onnx/releases/tag/tts-models)) and listed
in the [model documentation](https://k2-fsa.github.io/sherpa/onnx/). A whole-file
recognizer for one model looks like this:

```python
import sherpa_onnx

recognizer = sherpa_onnx.OfflineRecognizer.from_moonshine_v2(
    encoder=f"{model}/encoder_model.ort",
    decoder=f"{model}/decoder_model_merged.ort",
    tokens=f"{model}/tokens.txt",
    num_threads=2,
)
stream = recognizer.create_stream()
stream.accept_waveform(sample_rate, samples)  # mono floats in [-1, 1]
recognizer.decode_stream(stream)
text = stream.result.text
```

Each model family has its own constructor (`from_whisper`, `from_transducer`,
`from_sense_voice`, ...); the model's documentation page names it. `accept_waveform`
resamples to the model's rate itself.

### Models and storage

Models range from under 1 MB (Silero VAD) to hundreds of MB. Ship small ones with the app;
download large ones on first run into
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables#flet_app_storage_data),
Flet's persistent, app-private storage, and unpack them there. Python's `tarfile` reads the
`.tar.bz2` archives on both platforms. The example's `ensure_model()` unpacks into a
temporary folder and moves the result into place only when complete, so an interrupted
download does not leave a half-written model behind.

### Threading

Loading a model and decoding both block for a noticeable time: loading the 29 MB example
model takes a moment, and decoding scales with the audio length. Run them in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), end the
worker with [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), and keep
the recognizer for later calls instead of building it each time.

### Audio input and output

sherpa-onnx does not record or play audio in this build; it consumes and produces sample
lists. Recording from the microphone and playing synthesized speech are the job of Flet's
audio controls, with sherpa-onnx in between.

### App size

The wheel is 9–12 MB to download. Unpacked, it is about 28 MB per Android ABI (the
extension plus its own `libonnxruntime.so`, 22 MB on arm64-v8a) and one 27 MB module on
iOS, where ONNX Runtime is linked in. On Android, restricting
`[tool.flet.android] target_arch` to the ABIs you ship is the main lever. Models come on top.

### Other considerations

On a desktop, `flet run` installs PyPI's own sherpa-onnx wheels, which split the native
libraries into a separate `sherpa-onnx-core` package. The Python API is the same.

This wheel carries its own ONNX Runtime, so an app that also uses the `onnxruntime`
package ships two copies of it, one for each.

## Things to know

- **Pick the constructor the model's documentation names.** The example's moonshine model
  uses `from_moonshine_v2`. Construction does not reliably reject a mismatch: the older
  `from_moonshine` accepts the same files without error.
- **Messages from the native side go to stderr,** such as `Creating a resampler` when the
  audio's sample rate differs from the model's. They are informational.

## Build notes (maintainers)

### Recipe shape

A setup.py package that drives CMake, linking a prebuilt ONNX Runtime from
`flet-libonnxruntime` (a `host_build` dependency, so it is never a runtime requirement).
sherpa's own `cmake/onnxruntime.cmake` picks it up through `SHERPA_ONNXRUNTIME_INCLUDE_DIR`
and `SHERPA_ONNXRUNTIME_LIB_DIR`:

- Android gets the shared `libonnxruntime.so`, which sherpa installs into this wheel next to
  the extension.
- iOS gets a static `libonnxruntime.a`, linked into the extension, so nothing extra ships.
  The extension then also links CoreML, which this build of ONNX Runtime includes.

`SHERPA_ONNX_SPLIT_PYTHON_PACKAGE` stays unset, so the wheel does not depend on
`sherpa-onnx-core`, which has no iOS wheels. Three patches:

- `android-no-jni.patch` stops CMake from force-enabling the JNI library on Android, a 4 MB
  `.so` a Flet app cannot use.
- `android-preload-ort.patch` loads `libonnxruntime.so` before the extension, by path or by
  soname, because the extension has no RUNPATH.
- `onnxruntime-license.patch` adds ONNX Runtime's MIT licence at the project root, where
  setuptools picks it up into the wheel.

### Upgrade hazards

- **Keep `flet-libonnxruntime` on the ONNX Runtime version sherpa-onnx builds against,** as
  named in its `cmake/onnxruntime-android-*.cmake` (1.28.2 for 2.0.1), and update the
  `host_build` pin with it.
- **The ONNX Runtime zips have changed layout before.** 1.28.2's iOS zip has a new name and
  no wrapping folder; `flet-libonnxruntime` unpacks them as-is (`strip: 0`) and its build
  script names the paths.
- **PyPI publishes Android wheels for sherpa-onnx** (Python 3.14 only, split into
  `sherpa-onnx-core`). Ours wins ties at the same version through its build tag, but a newer
  upstream release outranks it in unpinned apps.

### Re-verification checklist

- Android wheels contain `sherpa_onnx/lib/libonnxruntime.so` and no
  `libsherpa-onnx-jni.so`; iOS wheels contain one extension, `otool -hv` reports `DYLIB`,
  and `nm -gU` finds `OrtGetApiBase` in it.
- Every wheel has `LICENSE-onnxruntime` in `dist-info/licenses` and no `sherpa-onnx-core`
  requirement.
- `test_vad_inference` passes rather than skips: it downloads Silero VAD and runs it.
- The example transcribes its sample to "Ask not what your country can do for you…" on
  both platforms.

### Coverage gaps

The device tests cover loading the extension and ONNX Runtime, the native config and buffer
objects, and real Silero VAD inference. Speech recognition runs only in the example; text
to speech, keyword spotting and speaker identification are compiled in but untested here.
The CoreML provider on iOS is untested. ONNX Runtime's third-party notices are in
`flet-libonnxruntime` but not in this wheel, which carries only its MIT licence. Timings
come from emulators and simulators, not phones.
