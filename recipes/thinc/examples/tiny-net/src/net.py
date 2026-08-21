import os
import time

import numpy
import thinc
from thinc.api import Config, get_current_ops, registry

CLASSES = ("arc", "loop", "curl")
PER_CLASS = 260
POINTS = PER_CLASS * len(CLASSES)
GEMM_SIZE = 256
MODEL_FILE = "tiny-net.bin"
VERSION = f"thinc {thinc.__version__} — {POINTS} points in {len(CLASSES)} spirals"

FALLBACK_CONFIG = """
[model]
@layers = "chain.v1"

[model.*.hidden]
@layers = "Relu.v1"
nO = 64
dropout = 0.1

[model.*.output]
@layers = "Softmax.v1"
nO = 3

[optimizer]
@optimizers = "Adam.v1"
learn_rate = 0.01

[loss]
@losses = "CategoricalCrossentropy.v3"
normalize = true

[training]
epochs = 30
batch_size = 32
"""


def backend():
    """Report the ops backend this device actually got, and whether BLIS is under it.

    thinc picks the backend at first use rather than at import, and a phone has no
    CUDA and no Metal, so the answer is always NumpyOps here. What is worth printing
    anyway is `use_blis`: with it on, a float32 `ops.gemm` leaves NumPy entirely and
    runs BLIS's kernels instead.
    """
    ops = get_current_ops()
    return {
        "ops": type(ops).__name__,
        "name": ops.name,
        "device": ops.device_type,
        "array module": ops.xp.__name__,
        "blis gemm": "on" if getattr(ops, "use_blis", False) else "off",
    }


def load_config(width):
    """Load the training config from assets, falling back to the copy in this file.

    A `.cfg` belongs in `src/assets/` rather than beside this module: assets are
    packaged as real files on both platforms, while a data file sitting inside a
    Python package is served from a zip on Android and `Config().from_disk` cannot
    read it. Returns the config and a label saying which copy was used.
    """
    assets = os.getenv("FLET_ASSETS_DIR")
    path = os.path.join(assets, "model.cfg") if assets else None
    if path and os.path.isfile(path):
        config, source = Config().from_disk(path), "assets/model.cfg"
    else:
        config, source = Config().from_str(FALLBACK_CONFIG), "built-in string"
    config["model"]["*"]["hidden"]["nO"] = int(width)
    return config, source


def spiral(seed=0):
    """Build three interleaved spiral arms as float32 features and one-hot targets.

    No straight line separates these arms, so accuracy climbing past a third is
    evidence that the hidden Relu layer is doing work rather than the output layer
    memorising a majority class.
    """
    rng = numpy.random.default_rng(seed)
    features = numpy.zeros((POINTS, 2), dtype="float32")
    targets = numpy.zeros((POINTS, len(CLASSES)), dtype="float32")
    for index in range(len(CLASSES)):
        radius = numpy.linspace(0.0, 1.0, PER_CLASS)
        angle = numpy.linspace(index * 4, (index + 1) * 4, PER_CLASS)
        angle = angle + rng.normal(0, 0.2, PER_CLASS)
        arm = slice(index * PER_CLASS, (index + 1) * PER_CLASS)
        features[arm, 0] = radius * numpy.sin(angle)
        features[arm, 1] = radius * numpy.cos(angle)
        targets[arm, index] = 1.0
    order = rng.permutation(POINTS)
    return features[order], targets[order]


def accuracy(model, features, targets):
    """Fraction of rows whose highest-scoring class is the right one."""
    predicted = model.predict(features).argmax(axis=1)
    return float((predicted == targets.argmax(axis=1)).mean())


def train(width):
    """Resolve the config into live objects, train, save, reload, and report.

    `registry.resolve` turns the four `@`-prefixed sections into a chained model, an
    Adam optimizer and a loss object, validating every other key against the
    signatures of the registered functions on the way. Everything after that is the
    canonical thinc loop: `begin_update` returns predictions and a callback, the
    callback takes the gradient of the loss and pushes it back through the layers,
    and `finish_update` hands the accumulated gradients to the optimizer.

    The save/reload round trip at the end is the part worth copying into a real app:
    a trained model is one to four kilobytes of msgpack at these widths, and
    reloading it needs a model built from the same config — but not a second
    `initialize`, since the file carries the layer dimensions with the weights.
    """
    config, source = load_config(width)
    resolved = registry.resolve(config)
    model, optimizer, loss = resolved["model"], resolved["optimizer"], resolved["loss"]
    epochs = resolved["training"]["epochs"]
    batch_size = resolved["training"]["batch_size"]

    features, targets = spiral()
    split = int(0.8 * len(features))
    train_x, train_y = features[:split], targets[:split]
    test_x, test_y = features[split:], targets[split:]

    model.initialize(X=train_x[:batch_size], Y=train_y[:batch_size])
    before = accuracy(model, test_x, test_y)

    started = time.perf_counter()
    for _ in range(epochs):
        for batch_x, batch_y in model.ops.multibatch(
            batch_size, train_x, train_y, shuffle=True
        ):
            guesses, backprop = model.begin_update(batch_x)
            backprop(loss.get_grad(guesses, batch_y))
            model.finish_update(optimizer)
    trained_ms = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    after = accuracy(model, test_x, test_y)
    predict_ms = (time.perf_counter() - started) * 1000

    path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), MODEL_FILE)
    model.to_disk(path)
    reloaded = registry.resolve(config)["model"]
    reloaded.from_disk(path)  # no initialize: the file carries the layer dimensions
    identical = bool(numpy.array_equal(reloaded.predict(test_x), model.predict(test_x)))

    return {
        "config": source,
        "layers": model.name,
        "rows": f"{len(train_x)} train / {len(test_x)} test",
        "accuracy": f"{before:.0%} to {after:.0%}",
        "trained": f"{trained_ms:.0f} ms over {epochs} epochs",
        "inference": f"{predict_ms:.2f} ms for {len(test_x)} rows",
        "saved": f"{os.path.getsize(path)} bytes, reload matches: "
        f"{'yes' if identical else 'no'}",
    }


def gemm_race(size=GEMM_SIZE):
    """Time thinc's BLIS gemm against NumPy's own matmul on the same float32 data.

    This is the measurement that does not survive the trip from a laptop: desktop
    NumPy is linked against a tuned BLAS and wins by a wide margin, while the mobile
    NumPy wheel is built with no BLAS at all. Both calls produce the same matrix, so
    the only question is which implementation gets there first on this device.
    """
    ops = get_current_ops()
    rng = numpy.random.default_rng(1)
    left = rng.random((size, size), dtype=numpy.float32)
    right = rng.random((size, size), dtype=numpy.float32)

    ops.gemm(left, right)  # untimed: BLIS initialises once, on its first call ever
    left @ right

    started = time.perf_counter()
    ops.gemm(left, right)
    blis_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    left @ right
    numpy_ms = (time.perf_counter() - started) * 1000
    return {
        f"ops.gemm {size}x{size}": f"{blis_ms:.2f} ms",
        f"numpy matmul {size}x{size}": f"{numpy_ms:.2f} ms",
    }
