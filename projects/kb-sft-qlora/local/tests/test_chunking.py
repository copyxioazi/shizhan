from kb_sft_data.chunking import clean_text, split_markdown


def test_clean_images_and_fullwidth_digits():
    text = "温度 １０ ℃。![示意图](http://192.168.72.129:9000/a.jpg)"
    cleaned = clean_text(text)
    assert "192.168" not in cleaned
    assert "[图片说明：示意图]" in cleaned
    assert "10" in cleaned


def test_split_markdown_keeps_table_whole():
    body = "# 手册\n\n## 参数\n\n" + "\n".join(f"| 项{i} | 值{i} |" for i in range(20))
    chunks = split_markdown(body, doc_id="doc")
    table = [c for c in chunks if c["is_table"]]
    assert table, chunks
    assert all("## 参数" in c["content"] for c in table)


def test_split_markdown_chunks_long_section():
    body = "# 手册\n\n## 说明\n\n" + ("这是说明。" * 200)
    chunks = split_markdown(body, doc_id="doc", chunk_size=250, overlap=50)
    assert len(chunks) > 3
    assert all(c["chunk_id"].startswith("doc:s") for c in chunks)
