def test_schema_validator_basic():
    """pydantic-core is the Rust validator backing pydantic v2. Build a
    small schema directly (no pydantic-shim) and validate a payload."""
    from pydantic_core import SchemaValidator, core_schema

    schema = core_schema.typed_dict_schema(
        {
            "name": core_schema.typed_dict_field(core_schema.str_schema()),
            "age": core_schema.typed_dict_field(core_schema.int_schema(ge=0)),
        }
    )
    v = SchemaValidator(schema)
    assert v.validate_python({"name": "Ada", "age": 37}) == {"name": "Ada", "age": 37}


def test_validation_error_raised():
    """Invalid input goes through the Rust error-formatting path."""
    from pydantic_core import SchemaValidator, ValidationError, core_schema

    v = SchemaValidator(core_schema.int_schema(ge=0))
    try:
        v.validate_python(-1)
    except ValidationError:
        return
    raise AssertionError("expected ValidationError for negative int with ge=0")
