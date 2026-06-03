def test_descriptor_pool():
    """protobuf ships a C++ implementation (`_message`) for runtime
    serialisation. Build a message type via the DescriptorPool API at
    runtime (no .proto file or generated code needed) and round-trip it."""
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

    # Define a message: `message Item { int32 id = 1; string name = 2; }`
    file_proto = descriptor_pb2.FileDescriptorProto()
    file_proto.name = "item.proto"
    file_proto.syntax = "proto3"
    item = file_proto.message_type.add()
    item.name = "Item"
    f1 = item.field.add()
    f1.name = "id"
    f1.number = 1
    f1.type = descriptor_pb2.FieldDescriptorProto.TYPE_INT32
    f1.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    f2 = item.field.add()
    f2.name = "name"
    f2.number = 2
    f2.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    f2.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    Item = message_factory.GetMessageClass(pool.FindMessageTypeByName("Item"))

    msg = Item(id=42, name="mobile-forge")
    blob = msg.SerializeToString()
    assert isinstance(blob, bytes)
    assert len(blob) > 0

    parsed = Item()
    parsed.ParseFromString(blob)
    assert parsed.id == 42
    assert parsed.name == "mobile-forge"


def test_well_known_timestamp():
    """Built-in Timestamp message exercises the bundled well-known types,
    which depend on the C++ extension being correctly loaded."""
    from google.protobuf.timestamp_pb2 import Timestamp

    t = Timestamp()
    t.seconds = 1_700_000_000
    t.nanos = 123_456_789
    blob = t.SerializeToString()

    rt = Timestamp()
    rt.ParseFromString(blob)
    assert rt.seconds == 1_700_000_000
    assert rt.nanos == 123_456_789
