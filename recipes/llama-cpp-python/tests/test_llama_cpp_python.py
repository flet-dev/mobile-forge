def test_native_lib_callable():
    """Call into the ctypes-loaded libllama without needing a GGUF model file.
    Proves the native library actually loaded and its symbols are callable."""
    import llama_cpp

    # const char * llama_print_system_info(void) — reports the compiled CPU
    # backend/feature set (e.g. NEON on arm64). Non-empty => the lib answered.
    info = llama_cpp.llama_print_system_info()
    assert isinstance(info, bytes) and len(info) > 0

    # A couple of trivial capability queries through the C ABI.
    assert isinstance(llama_cpp.llama_max_devices(), int)
    assert isinstance(llama_cpp.llama_supports_mmap(), bool)

    # Backend init/free round-trip exercises ggml setup teardown.
    llama_cpp.llama_backend_init()
    llama_cpp.llama_backend_free()
