# sherpa-onnx offline transcription

Speech-to-text that runs on the device. On first run the app downloads a small English
model, [moonshine tiny](https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models)
(29 MB), into the app's storage. It then transcribes the recording that ships inside the
model archive, a 3.8-second clip, and shows the text and how long decoding took. After the
first run nothing touches the network.

What it demonstrates:

- **Fetching a model once.** `ensure_model()` in [`src/speech.py`](src/speech.py) downloads
  the `.tar.bz2` release into
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables#flet_app_storage_data),
  unpacks it in a temporary folder and moves it into place only when complete, so an
  interrupted download is retried on the next run instead of leaving a broken model.
- **Recognizing a file.** `transcribe()` reads a 16-bit WAV with the standard library and
  hands the samples to an `OfflineRecognizer`. sherpa-onnx resamples to the model's rate
  itself, so the 24 kHz sample needs no conversion. numpy is not required.
- **Work off the UI thread.** Download, model loading and decoding all run in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), and
  the recognizer is kept for later taps, since loading it is the slow part.

To transcribe your own audio, pass any mono 16-bit WAV path to `transcribe()`.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```
