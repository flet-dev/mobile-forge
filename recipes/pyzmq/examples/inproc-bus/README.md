# pyzmq inproc bus

A work queue built out of ZeroMQ sockets inside one Flet app. The UI thread pushes sixteen
256 KB jobs, one to four worker threads pull them and compress each one with
[`bz2`](https://docs.python.org/3/library/bz2.html), and a collector thread drains the results
onto the screen. Nothing leaves the process: every socket speaks
[`inproc://`](https://libzmq.readthedocs.io/en/latest/zmq_inproc.html), the transport that needs
no port, no permission and no network stack. Move the slider to change the worker count.

What it demonstrates:

- **A PUSH/PULL work queue** — one bound
  [PUSH](https://zguide.zeromq.org/docs/chapter1/#Divide-and-Conquer) socket hands each message to
  exactly one connected PULL socket, round robin, and the jobs column shows it: four workers, four
  jobs each. PUSH counts messages rather than measuring who is busy, so uneven jobs would back one
  worker's queue up while another idles. Each job travels as two frames through
  [`send_multipart(..., copy=False)`](https://pyzmq.readthedocs.io/en/latest/api/zmq.html#zmq.Socket.send_multipart),
  which above pyzmq's 64 KB copy threshold hands libzmq the buffer itself rather than a duplicate.
- **Stopping threads that are blocked on a socket** — a work queue delivers to one peer, which is
  the wrong shape for "everyone stop", so the control channel is a PUB socket and one
  [`send()`](https://pyzmq.readthedocs.io/en/latest/api/zmq.html#zmq.Socket.send) clears however
  many workers are running. Each worker watches the job queue and that channel together with a
  [`zmq.Poller`](https://pyzmq.readthedocs.io/en/latest/api/zmq.html#zmq.Poller), and sliding the
  workers to zero ends every one of them within a millisecond. A bare `recv()` would hold its
  slot in the page executor for the life of the app, with nothing short of tearing down the
  whole context able to interrupt it.
- **One context, one socket per thread** — every socket comes from the single
  [`zmq.Context.instance()`](https://pyzmq.readthedocs.io/en/latest/api/zmq.html#zmq.Context.instance)
  in `bus.py`, because an `inproc` name only resolves inside the context that owns it, and each
  worker builds its own sockets inside itself:
  [ZeroMQ sockets are not thread-safe](https://libzmq.readthedocs.io/en/latest/zmq_socket.html),
  and sharing one is a crash rather than an exception.
- **Compute off the UI thread** — workers and collector run in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the run
  button disabled and a spinner up, and every background repaint ends in the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a thread needs. The
  slider fires on
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end), so a drag
  restarts the workers once rather than once per step.

Watch the busy column against the elapsed time: four workers report more compression between them
than the whole batch took — around 260 ms of work inside 70 ms of wall clock on a desktop run —
because `bz2` releases the GIL. Pure-Python work in the same pipeline still gets a responsive UI
and a tidy structure, but four workers take exactly as long as one.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator.
**The iOS builds are commented out because they cannot link today** — the published iOS
wheels ship an `MH_BUNDLE` extension; see the recipe page's Install section.

```bash
# Android
uv run flet build apk

# iOS — fails at link time today, see the recipe page
# uv run flet build ipa

# iOS-Simulator — same
# uv run flet build ios-simulator
```
