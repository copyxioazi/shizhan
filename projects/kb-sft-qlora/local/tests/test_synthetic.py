from kb_sft_data.chunking import split_markdown
from kb_sft_data.corpus import parse_front_matter
from kb_sft_data.synthetic import DOC_SPECS, render_doc


def test_render_and_chunk():
    spec = DOC_SPECS[0]
    text = render_doc(spec)
    meta, body = parse_front_matter(text)
    assert meta["doc_id"] == spec["doc_id"]
    assert meta["split"] == spec["split"]
    chunks = split_markdown(body, doc_id=meta["doc_id"])
    assert len(chunks) >= 4
    assert all(c["doc_id"] == spec["doc_id"] for c in chunks)


def test_all_specs_render():
    for spec in DOC_SPECS:
        text = render_doc(spec)
        assert len(text) > 1200, spec["doc_id"]
        meta, _ = parse_front_matter(text)
        assert meta["doc_id"] == spec["doc_id"]
