from kb_sft_data.templates import (
    citation_block,
    context_block,
    remap_labels,
    user_content,
)


def _chunk(cid, title="设备", content="温度 10 ℃。"):
    return {
        "chunk_id": cid, "source": "local", "file_title": "手册",
        "title": title, "display_title": title.replace("## ", ""),
        "url": "https://example.com/doc", "content": content,
    }


def test_context_block_numbering():
    text = context_block([_chunk("a"), _chunk("b")])
    assert text.startswith("[1][local][手册]")
    assert "[2][local][手册]" in text


def test_user_content_contains_question():
    text = user_content([_chunk("a")], ["设备A"], "温度要求？")
    assert "【参考内容】" in text
    assert "【相关实体】" in text
    assert "温度要求？" in text


def test_remap_and_citation_block():
    assert remap_labels("结论[C1][C2]", {1: 3, 2: 1}) == "结论[3][1]"
    block = citation_block([(3, _chunk("a"))])
    assert block.startswith("【参考来源】")
    assert "[3] 手册 | 设备 | https://example.com/doc" in block
