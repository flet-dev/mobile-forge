def test_open_and_read(tmp_path):
    """PyMuPDF wraps the MuPDF C library. Create a one-page PDF in memory
    then re-open it and read the text back."""
    import fitz  # PyMuPDF

    # Create a fresh document with one page containing known text.
    src = fitz.open()
    page = src.new_page()
    page.insert_text((72, 72), "Hello mobile-forge")
    pdf_bytes = src.tobytes()
    src.close()

    # Re-open from bytes and read the text back.
    dst = fitz.open(stream=pdf_bytes, filetype="pdf")
    assert dst.page_count == 1
    text = dst[0].get_text()
    dst.close()

    assert "Hello mobile-forge" in text


def test_metadata():
    """Document.metadata is a Python wrapper around MuPDF's
    pdf_dict_get_inheritable — confirms basic dict roundtrip."""
    import fitz

    doc = fitz.open()
    doc.new_page()
    doc.set_metadata({"title": "test", "author": "ci"})

    blob = doc.tobytes()
    doc.close()

    rt = fitz.open(stream=blob, filetype="pdf")
    md = rt.metadata
    rt.close()

    assert md["title"] == "test"
    assert md["author"] == "ci"
