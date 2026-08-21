import bz2
import random
import time

import zmq

# One context for the whole app. inproc endpoints are resolved inside the
# context that owns them, so two contexts connected to the same name never see
# each other -- and never say so either.
CONTEXT = zmq.Context.instance()

JOBS = "inproc://jobs"
RESULTS = "inproc://results"
CONTROL = "inproc://control"

JOB_COUNT = 16
CHUNK = 256 * 1024
LEVEL = 9

VERSION = (
    f"pyzmq {zmq.__version__} · libzmq {zmq.zmq_version()} · "
    f"{JOB_COUNT} × {CHUNK // 1024} KB, bz2 level {LEVEL}"
)

# Text-like bytes: random letters, spaces and punctuation, which bz2 gets down
# to about two thirds. Built once as one buffer, because a job is a memoryview
# into it rather than a copy of it.
BLOB = (
    random.Random(7)
    .randbytes(JOB_COUNT * CHUNK)
    .translate(b"abcdefghijklmnopqrstuvwxyz .,;\n\t" * 8)
)


def job_queue():
    """Open the PUSH end of the work queue, on the thread that will submit jobs.

    `SNDTIMEO` is the load-bearing line. A PUSH socket with no PULL peer
    connected blocks in `send()` until one arrives -- forever, in practice --
    and this socket is used from the UI thread, so the default would freeze the
    app whenever the workers are stopped. With the timeout, `send()` raises
    `zmq.Again` instead and the caller stays responsive.
    """
    queue = CONTEXT.socket(zmq.PUSH)
    queue.setsockopt(zmq.SNDTIMEO, 250)
    queue.bind(JOBS)
    return queue


def control():
    """Open the PUB end of the stop channel, on the thread that will publish.

    A stop is fan-out rather than a hand-off: one `send()` has to reach every
    worker that happens to be running, which is what PUB/SUB does and what
    PUSH/PULL cannot -- a PUSH would give the message to exactly one of them.
    """
    stop = CONTEXT.socket(zmq.PUB)
    stop.bind(CONTROL)
    return stop


def submit(queue):
    """Push one job per chunk of the blob and report how many went out.

    Each job is a two-frame message: an index and the bytes to compress.
    `copy=False` on a frame larger than pyzmq's 64 KB copy threshold hands
    libzmq the buffer itself, so a 256 KB job costs a pointer rather than a
    memcpy -- safe here because `BLOB` is immutable and nothing rewrites it
    while the queue still holds a reference.

    The count comes back rather than the constant because it is not always
    `JOB_COUNT`: with no worker connected the first send times out, and the
    caller needs to know that nothing was queued.
    """
    view = memoryview(BLOB)
    for index in range(JOB_COUNT):
        chunk = view[index * CHUNK : (index + 1) * CHUNK]
        try:
            queue.send_multipart([b"%d" % index, chunk], copy=False)
        except zmq.Again:
            return index
    return JOB_COUNT


def worker(name):
    """Pull jobs, compress them, push results back, until told to stop.

    Every socket is created here, inside the thread that uses it, and never
    handed anywhere else: a `Context` is thread-safe but a `Socket` is not, and
    sharing one is not an error you get to catch. Four threads sending on one
    socket segfaulted the interpreter while this example was being written.

    The poller is what makes the thread stoppable. A blocking `recv()` on the
    job queue would hold this thread for the rest of the app's life, since
    nothing else can interrupt it. Polling both sockets and checking the stop
    channel first means pressing Stop abandons whatever is still queued in this
    worker's pipe -- those jobs are gone, which is exactly what a PUSH queue
    does when a peer disappears.

    `bz2.compress` releases the GIL, so two workers really do halve the wall
    clock here. Pure-Python work would not: inproc buys structure and a
    responsive UI, not parallelism.
    """
    jobs = CONTEXT.socket(zmq.PULL)
    jobs.connect(JOBS)
    done = CONTEXT.socket(zmq.PUSH)
    done.connect(RESULTS)
    stop = CONTEXT.socket(zmq.SUB)
    stop.connect(CONTROL)
    stop.subscribe(b"")

    poller = zmq.Poller()
    poller.register(jobs, zmq.POLLIN)
    poller.register(stop, zmq.POLLIN)
    try:
        while True:
            ready = dict(poller.poll())
            if stop in ready:
                return
            index, chunk = jobs.recv_multipart(copy=False)
            started = time.perf_counter()
            packed = bz2.compress(chunk.buffer, LEVEL)
            done.send_multipart(
                [
                    name.encode(),
                    bytes(index.buffer),
                    b"%.1f" % ((time.perf_counter() - started) * 1000),
                    b"%d" % len(packed),
                ]
            )
    finally:
        for socket in (jobs, done, stop):
            socket.close()


def results():
    """Yield one dict per finished job, forever, blocking in between.

    This binds the results endpoint and is never restarted, because an inproc
    name can only be bound by one live socket: stopping and restarting a
    collector would race its own `close()` and fail the next `bind()` with
    "Address already in use". Workers come and go around it.
    """
    sink = CONTEXT.socket(zmq.PULL)
    sink.bind(RESULTS)
    try:
        while True:
            name, index, elapsed, packed = sink.recv_multipart()
            yield {
                "worker": name.decode(),
                "index": int(index),
                "ms": float(elapsed),
                "packed": int(packed),
            }
    finally:
        sink.close()
