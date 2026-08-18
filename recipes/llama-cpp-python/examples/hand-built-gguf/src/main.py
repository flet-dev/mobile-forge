"""Write a GGUF language model on this device, generate from it, and check it against numpy."""

import ctypes
import os
import platform
import struct
import time

import flet as ft
import llama_cpp
import numpy as np

WIDTHS = (32, 64, 128, 256, 512)

HEADS = 4

PIECES = 8

EPSILON = 1e-5

CONTEXT = 256

BATCH = 32

PROMPT = b"llama"

NEW_TOKENS = 24

TEMPERATURE = 0.8

SEED = 1234

TOLERANCE = 1e-4

ALIGNMENT = 32

UINT32, INT32, FLOAT32, STRING, ARRAY = 4, 5, 6, 8, 9

THREADS = max(1, min(4, (os.cpu_count() or 2) // 2))

STORAGE = os.getenv("FLET_APP_STORAGE_DATA", ".")

STAGE_WEIGHTS = (5, 3, 8)

QUANT_WEIGHTS = (3, 5, 4)


def gguf_string(raw):
    """A GGUF string: a little-endian u64 byte count, then the bytes."""
    return struct.pack("<Q", len(raw)) + raw


def gguf_pair(key, kind, payload):
    """One key/value pair of the GGUF metadata block."""
    return gguf_string(key.encode()) + struct.pack("<I", kind) + payload


def gguf_array(kind, count, payload):
    """A GGUF array value: element type, element count, then the packed elements."""
    return struct.pack("<IQ", kind, count) + payload


def vocabulary():
    """A 267-entry SentencePiece vocabulary: three control tokens, all 256 bytes, eight pieces.

    The `<0xNN>` byte tokens are not filler. llama.cpp's SPM tokenizer falls back to
    them for anything it cannot match and looks each one up with `unordered_map::at`,
    so a vocabulary without them throws a C++ exception on the first `tokenize` call —
    which aborts the process rather than raising anything Python can catch.
    """
    tokens = [b"<unk>", b"<s>", b"</s>"] + [b"<0x%02X>" % byte for byte in range(256)]
    kinds = [2, 3, 3] + [6] * 256
    tokens += [("▁" + chr(0x61 + index)).encode() for index in range(PIECES)]
    return tokens, kinds + [1] * PIECES


def tensors(width):
    """Every tensor of a one-block llama-architecture model, keyed by GGUF tensor name.

    Each array is (outputs, inputs) so a plain `W @ x` is the forward direction; the
    GGUF tensor table records the reversed shape, which is ggml's `ne` order.
    """
    rng = np.random.default_rng(width)
    hidden = 2 * width
    vocab = 3 + 256 + PIECES

    def normal(rows, columns):
        """A weight matrix, scaled small so the forward pass stays numerically tame."""
        return (rng.standard_normal((rows, columns)) * 0.02).astype(np.float32)

    return {
        "token_embd.weight": normal(vocab, width),
        "blk.0.attn_norm.weight": np.ones(width, dtype=np.float32),
        "blk.0.attn_q.weight": normal(width, width),
        "blk.0.attn_k.weight": normal(width, width),
        "blk.0.attn_v.weight": normal(width, width),
        "blk.0.attn_output.weight": normal(width, width),
        "blk.0.ffn_norm.weight": np.ones(width, dtype=np.float32),
        "blk.0.ffn_gate.weight": normal(hidden, width),
        "blk.0.ffn_up.weight": normal(hidden, width),
        "blk.0.ffn_down.weight": normal(width, hidden),
        "output_norm.weight": np.ones(width, dtype=np.float32),
        "output.weight": normal(vocab, width),
    }


def write_gguf(path, width):
    """Serialise a complete GGUF v3 file and return its predicted size and parameter count.

    Header, metadata, tensor table and `ALIGNMENT`-padded float32 tensor data, written
    with `struct` and numpy alone — there is no `gguf` package on this index and none is
    needed. The predicted size is returned so the app can check it against the file that
    actually landed on disk.
    """
    weights = tensors(width)
    tokens, kinds = vocabulary()
    metadata = [
        gguf_pair("general.architecture", STRING, gguf_string(b"llama")),
        gguf_pair("general.name", STRING, gguf_string(b"flet-hand-built")),
        gguf_pair("general.alignment", UINT32, struct.pack("<I", ALIGNMENT)),
        gguf_pair("llama.block_count", UINT32, struct.pack("<I", 1)),
        gguf_pair("llama.context_length", UINT32, struct.pack("<I", CONTEXT)),
        gguf_pair("llama.embedding_length", UINT32, struct.pack("<I", width)),
        gguf_pair("llama.feed_forward_length", UINT32, struct.pack("<I", 2 * width)),
        gguf_pair("llama.attention.head_count", UINT32, struct.pack("<I", HEADS)),
        gguf_pair("llama.attention.head_count_kv", UINT32, struct.pack("<I", HEADS)),
        gguf_pair(
            "llama.attention.layer_norm_rms_epsilon",
            FLOAT32,
            struct.pack("<f", EPSILON),
        ),
        gguf_pair(
            "llama.rope.dimension_count", UINT32, struct.pack("<I", width // HEADS)
        ),
        gguf_pair("tokenizer.ggml.model", STRING, gguf_string(b"llama")),
        gguf_pair(
            "tokenizer.ggml.tokens",
            ARRAY,
            gguf_array(STRING, len(tokens), b"".join(gguf_string(t) for t in tokens)),
        ),
        gguf_pair(
            "tokenizer.ggml.scores",
            ARRAY,
            gguf_array(
                FLOAT32, len(tokens), np.zeros(len(tokens), np.float32).tobytes()
            ),
        ),
        gguf_pair(
            "tokenizer.ggml.token_type",
            ARRAY,
            gguf_array(INT32, len(kinds), np.array(kinds, np.int32).tobytes()),
        ),
        gguf_pair("tokenizer.ggml.bos_token_id", UINT32, struct.pack("<I", 1)),
        gguf_pair("tokenizer.ggml.eos_token_id", UINT32, struct.pack("<I", 2)),
    ]

    table, blobs, offset = b"", [], 0
    for name, array in weights.items():
        shape = array.shape[::-1]
        table += (
            gguf_string(name.encode())
            + struct.pack("<I", len(shape))
            + b"".join(struct.pack("<Q", size) for size in shape)
            + struct.pack("<IQ", 0, offset)
        )
        raw = array.tobytes()
        padding = -len(raw) % ALIGNMENT
        blobs.append(raw + b"\0" * padding)
        offset += len(raw) + padding

    header = b"GGUF" + struct.pack("<IQQ", 3, len(weights), len(metadata))
    header += b"".join(metadata) + table
    header += b"\0" * (-len(header) % ALIGNMENT)
    with open(path, "wb") as handle:
        handle.write(header)
        for blob in blobs:
            handle.write(blob)
    return len(header) + offset, sum(int(array.size) for array in weights.values())


def read_gguf(path):
    """Parse a GGUF file back into its metadata and its float32 tensors.

    The cross-check has to read the weights from the file rather than reuse the arrays
    that produced it, or it would only be comparing numpy with itself.
    """
    raw = open(path, "rb").read()
    _, count, pairs = struct.unpack_from("<IQQ", raw, 4)
    cursor = 24

    def take_string():
        """The next length-prefixed string, advancing the cursor past it."""
        nonlocal cursor
        (length,) = struct.unpack_from("<Q", raw, cursor)
        cursor += 8 + length
        return raw[cursor - length : cursor]

    def take_value(kind):
        """The next metadata value of type `kind`, advancing the cursor past it."""
        nonlocal cursor
        if kind == STRING:
            return take_string()
        if kind == ARRAY:
            element, length = struct.unpack_from("<IQ", raw, cursor)
            cursor += 12
            return [take_value(element) for _ in range(length)]
        (value,) = struct.unpack_from(
            {UINT32: "<I", INT32: "<i", FLOAT32: "<f"}[kind], raw, cursor
        )
        cursor += 4
        return value

    metadata = {}
    for _ in range(pairs):
        key = take_string().decode()
        (kind,) = struct.unpack_from("<I", raw, cursor)
        cursor += 4
        metadata[key] = take_value(kind)

    table = []
    for _ in range(count):
        name = take_string().decode()
        (rank,) = struct.unpack_from("<I", raw, cursor)
        cursor += 4
        shape = struct.unpack_from("<" + "Q" * rank, raw, cursor)
        cursor += 8 * rank
        offset = struct.unpack_from("<IQ", raw, cursor)[1]
        cursor += 12
        table.append((name, shape, offset))

    base = cursor + -cursor % ALIGNMENT
    weights = {
        name: np.frombuffer(
            raw, np.float32, int(np.prod(shape)), base + offset
        ).reshape(shape[::-1])
        for name, shape, offset in table
    }
    return metadata, weights


def reference_logits(metadata, weights, tokens):
    """Logits for the last of `tokens`, recomputed in float64 numpy straight from the file.

    The whole llama forward pass for one block: RMS norm, RoPE on the query and key
    halves, causal attention, SwiGLU feed-forward, a final norm and the output
    projection. This is the answer llama.cpp's is judged against, so it deliberately
    shares no code with it.
    """
    width = metadata["llama.embedding_length"]
    heads = metadata["llama.attention.head_count"]
    head = width // heads
    inverse = 1.0 / (10000.0 ** (np.arange(0, head, 2, dtype=np.float64) / head))

    def rms(vector, gain):
        """Root-mean-square normalisation, the layer norm llama uses."""
        return vector / np.sqrt((vector * vector).mean() + EPSILON) * gain

    states = weights["token_embd.weight"][list(tokens)].astype(np.float64)
    keys, values = [], []
    for position, state in enumerate(states):
        normed = rms(state, weights["blk.0.attn_norm.weight"])
        query = weights["blk.0.attn_q.weight"] @ normed
        key = weights["blk.0.attn_k.weight"] @ normed
        value = weights["blk.0.attn_v.weight"] @ normed
        cosine, sine = np.cos(position * inverse), np.sin(position * inverse)
        for vector in (query, key):
            split = vector.reshape(heads, head)
            even, odd = split[:, 0::2].copy(), split[:, 1::2].copy()
            split[:, 0::2] = even * cosine - odd * sine
            split[:, 1::2] = even * sine + odd * cosine
        keys.append(key.reshape(heads, head))
        values.append(value.reshape(heads, head))
        scores = (query.reshape(heads, 1, head) * np.stack(keys, 1)).sum(-1) / np.sqrt(
            head
        )
        scores = np.exp(scores - scores.max(-1, keepdims=True))
        scores /= scores.sum(-1, keepdims=True)
        attended = (scores[:, :, None] * np.stack(values, 1)).sum(1).reshape(width)
        state = state + weights["blk.0.attn_output.weight"] @ attended
        normed = rms(state, weights["blk.0.ffn_norm.weight"])
        gate = weights["blk.0.ffn_gate.weight"] @ normed
        up = weights["blk.0.ffn_up.weight"] @ normed
        swiglu = (gate / (1 + np.exp(-gate))) * up
        states[position] = state + weights["blk.0.ffn_down.weight"] @ swiglu
    return weights["output.weight"] @ rms(states[-1], weights["output_norm.weight"])


def quantize(source, target, ftype):
    """Quantise a GGUF in place on the device and return the resulting file size."""
    params = llama_cpp.llama_model_quantize_default_params()
    params.ftype = ftype
    params.nthread = THREADS
    if llama_cpp.llama_model_quantize(
        source.encode(), target.encode(), ctypes.byref(params)
    ):
        return 0
    return os.path.getsize(target)


def row(values, weights):
    """One table row, laid out by column weight so it fits a phone."""
    return ft.Row(
        controls=[
            ft.Text(value, size=11, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def main(page: ft.Page):
    """Build a model at the chosen width, run it, and report what came back.

    Everything on screen is computed here, on this device: the model file, the tokens
    llama.cpp generated from it, whether its logits agree with an independent numpy
    forward pass, and what the same weights cost once quantised. The weights are
    random, so the tokens are meaningless by construction — the pipeline is the point,
    not the output.
    """

    def show_width():
        """Report the model the next run will build, as the slider moves."""
        chosen = WIDTHS[int(size.value)]
        caption.value = f"embedding width {chosen}, 1 block, {HEADS} heads"

    def start():
        """Hand one run to a background thread and lock the slider while it works.

        Driven by the slider's on_change_end so one gesture means one run. The guard is
        set here rather than in the worker because this body is synchronous where
        `run_thread` only schedules: a `disabled` set inside the worker would not have
        reached the client before the next gesture arrived.
        """
        if size.disabled:
            return
        size.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Write the model, load it, generate, cross-check, quantise, and rebuild the tables.

        Worth a thread: every llama.cpp call here releases the GIL, so the UI keeps its
        frames. The `try/except` is not optional — `page.run_thread` discards whatever a
        worker raises, so a failure would look like a screen that simply stopped
        updating — and the panels are cleared on the way out so the previous run's
        numbers cannot sit under this run's error.
        """
        path = os.path.join(STORAGE, "hand-built.gguf")
        try:
            width = WIDTHS[int(size.value)]
            clock = time.perf_counter()
            predicted, parameters = write_gguf(path, width)
            write_ms = (time.perf_counter() - clock) * 1000
            written = os.path.getsize(path)

            clock = time.perf_counter()
            llm = llama_cpp.Llama(
                path,
                n_ctx=CONTEXT,
                n_batch=BATCH,
                n_ubatch=BATCH,
                n_threads=THREADS,
                n_threads_batch=THREADS,
                n_gpu_layers=0,
                logits_all=True,
                seed=SEED,
                verbose=False,
                # An f32 KV cache rather than llama.cpp's f16 default. At f16 the
                # cache alone is the entire llama.cpp-vs-numpy gap — 4.1e-04 of the
                # logit range against 2.6e-07 here — so the tolerance would have to
                # be loose enough to hide a genuine arithmetic fault.
                type_k=llama_cpp.GGML_TYPE_F32,
                type_v=llama_cpp.GGML_TYPE_F32,
            )
            load_ms = (time.perf_counter() - clock) * 1000
            try:
                tokens = llm.tokenize(PROMPT)
                clock = time.perf_counter()
                llm.reset()
                llm.eval(tokens)
                eval_ms = (time.perf_counter() - clock) * 1000
                actual = np.array(llm.scores[llm.n_tokens - 1, :], dtype=np.float64)

                clock = time.perf_counter()
                metadata, weights = read_gguf(path)
                expected = reference_logits(metadata, weights, tokens)
                check_ms = (time.perf_counter() - clock) * 1000

                clock = time.perf_counter()
                # zip() is the hard bound: max_tokens is not one, because the completion
                # loop skips its own limit check while a multi-byte character is open.
                produced = [
                    token
                    for _, token in zip(
                        range(NEW_TOKENS), llm.generate(tokens, temp=TEMPERATURE)
                    )
                ]
                generate_ms = (time.perf_counter() - clock) * 1000
                model_bytes = llama_cpp.llama_model_size(llm.model)
                model_parameters = llama_cpp.llama_model_n_params(llm.model)
                context = llm.n_ctx()
                logits_bytes = llm.scores.nbytes
                # The three terms a real model's footprint is made of. The KV cache
                # is the one that surprises people: it scales with n_ctx, not with
                # the weights, and llama.cpp allocates all of it up front.
                kv_bytes = context * width * 2 * 4
            finally:
                llm.close()

            quantised = [("F32 (source)", written, f"{written * 8 / parameters:.2f}")]
            for name, ftype in (
                ("Q8_0", llama_cpp.LLAMA_FTYPE_MOSTLY_Q8_0),
                ("Q4_0", llama_cpp.LLAMA_FTYPE_MOSTLY_Q4_0),
            ):
                target = os.path.join(STORAGE, f"hand-built-{name.lower()}.gguf")
                got = quantize(path, target, ftype)
                quantised.append(
                    (name, got, f"{got * 8 / parameters:.2f}" if got else "failed")
                )

            difference = float(np.abs(actual - expected).max())
            relative = difference / float(np.abs(expected).max())
            agreed = int(actual.argmax()) == int(expected.argmax())
            passed = agreed and relative < TOLERANCE
            verdict.value = (
                f"{'PASS' if passed else 'FAIL'} · llama.cpp vs numpy: top token "
                f"{'agrees' if agreed else 'DIFFERS'} · max|difference| {difference:.2e} "
                f"= {relative:.1e} of the logit range, against a {TOLERANCE:.0e} tolerance"
            )
            verdict.color = ft.Colors.GREEN if passed else ft.Colors.RED

            stages.controls = [
                row(("stage", "ms", "result"), STAGE_WEIGHTS),
                ft.Divider(height=1),
                row(
                    (
                        "write GGUF",
                        f"{write_ms:,.0f}",
                        f"{written:,} B, {parameters:,} params",
                    ),
                    STAGE_WEIGHTS,
                ),
                row(
                    (
                        "load",
                        f"{load_ms:,.0f}",
                        f"llama_model_size {model_bytes:,} B / {model_parameters:,} params",
                    ),
                    STAGE_WEIGHTS,
                ),
                row(
                    ("eval", f"{eval_ms:,.0f}", f"{len(tokens)} prompt tokens"),
                    STAGE_WEIGHTS,
                ),
                row(
                    (
                        "numpy check",
                        f"{check_ms:,.0f}",
                        "forward pass recomputed from the file",
                    ),
                    STAGE_WEIGHTS,
                ),
                row(
                    (
                        "generate",
                        f"{generate_ms:,.0f}",
                        f"{len(produced)} tokens, "
                        f"{len(produced) / (generate_ms / 1000):,.1f}/s: {produced[:6]}…",
                    ),
                    STAGE_WEIGHTS,
                ),
            ]
            quantisation.controls = [
                row(("type", "file bytes", "bits/weight (file)"), QUANT_WEIGHTS),
                ft.Divider(height=1),
                *(
                    row((name, f"{got:,}", bits), QUANT_WEIGHTS)
                    for name, got, bits in quantised
                ),
            ]
            footer.value = (
                f"memory: weights {model_bytes:,} B + KV cache {kv_bytes:,} B "
                f"(n_ctx {context} × 1 block × {width}, K and V, f32) + Python logits "
                f"buffer {logits_bytes:,} B · predicted file size {predicted:,} B, on "
                f"disk {written:,} B · asked for n_ctx {CONTEXT}, got {context} · "
                f"n_batch {BATCH} · weights are random, so the generated tokens are "
                "noise: the pipeline is the point"
            )
        except Exception as error:
            stages.controls = []
            quantisation.controls = []
            footer.value = ""
            verdict.color = ft.Colors.RED
            verdict.value = f"{type(error).__name__}: {error}"

        size.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(
        title=ft.Text("llama.cpp hand-built GGUF"), center_title=True
    )
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"llama-cpp-python {llama_cpp.__version__} · numpy "
                        f"{np.__version__} · Python {platform.python_version()} · "
                        f"{page.platform.value} · platform.system() = {platform.system()}",
                        size=11,
                    ),
                    ft.Text(
                        "llama_print_system_info(): "
                        + llama_cpp.llama_print_system_info().decode(
                            "utf-8", "replace"
                        ),
                        size=11,
                    ),
                    ft.Text(
                        f"library: {llama_cpp.llama_cpp._lib._name} · mmap "
                        f"{llama_cpp.llama_supports_mmap()} · gpu_offload "
                        f"{llama_cpp.llama_supports_gpu_offload()} · os.cpu_count() "
                        f"{os.cpu_count()} · using {THREADS} threads",
                        size=11,
                    ),
                    ft.Text(f"model written to {STORAGE}", size=11),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    size := ft.Slider(
                        min=0,
                        max=len(WIDTHS) - 1,
                        value=2,
                        divisions=len(WIDTHS) - 1,
                        on_change=show_width,
                        on_change_end=start,
                    ),
                    verdict := ft.Text(size=12),
                    ft.Divider(),
                    stages := ft.Column(spacing=2),
                    ft.Divider(),
                    quantisation := ft.Column(spacing=2),
                    footer := ft.Text(size=11),
                ],
            ),
        )
    )

    show_width()
    start()


if __name__ == "__main__":
    ft.run(main)
