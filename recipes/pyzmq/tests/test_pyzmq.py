def test_inproc_pair():
    """A PAIR socket over inproc:// exercises Context + Socket + send/recv through
    the compiled libzmq backend, without touching the network (no ports/sockets,
    so it's safe on a sandboxed emulator/simulator)."""
    import zmq

    ctx = zmq.Context()
    sender = ctx.socket(zmq.PAIR)
    receiver = ctx.socket(zmq.PAIR)
    sender.bind("inproc://pyzmq-test")
    receiver.connect("inproc://pyzmq-test")

    sender.send(b"hello from pyzmq")
    assert receiver.recv() == b"hello from pyzmq"

    sender.close()
    receiver.close()
    ctx.term()
