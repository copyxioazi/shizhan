from kb_sft_data.renderer import build_sample
from kb_sft_data.templates import SYSTEM_PROMPT, user_content
from kb_sft_data.verifier import verify_sample


def _context():
    return {
        "idx": 1, "chunk_id": "doc:s00:p0", "doc_id": "doc", "source": "local",
        "file_title": "手册", "title": "## 设备", "display_title": "设备",
        "url": "https://example.com/doc",
        "content": "设备应在温度 10 °C 至 32 °C、湿度 20% 至 80% 的环境中运行。",
        "score": 1.0, "rank": 1, "injected": False, "source_type": "synthetic",
        "item_name": "设备A", "doc_type": "safety",
    }


def _sample():
    contexts = [_context()]
    question = "设备的工作温度是多少？"
    candidate = {
        "question": question,
        "hyde_text": "10 °C 至 32 °C",
        "answer_text": "设备应在 10 °C 至 32 °C 的环境中运行[C1]。",
        "claims": [{"claim_id": "c1", "text": "10 °C 至 32 °C", "evidence_labels": ["C1"]}],
        "missing_info": [],
        "conflict_values": [],
        "format_template": "plain",
        "difficulty": "easy",
    }
    bundle = {
        "bundle_id": "b1", "split": "dev", "task_type": "faithful", "subtype": "single_fact",
        "evidence_chunk_ids": ["doc:s00:p0"], "evidence_labels": {"C1": "doc:s00:p0"},
        "expected_behavior": "answer", "item_names": ["设备A"],
    }
    return build_sample(candidate, bundle, contexts)


def test_valid_sample_passes():
    sample = _sample()
    ok, reasons = verify_sample(sample)
    assert ok, reasons


def test_unsupported_number_fails():
    sample = _sample()
    sample["messages"][2]["content"] = sample["messages"][2]["content"].replace("10 °C", "99 °C")
    ok, reasons = verify_sample(sample)
    assert not ok
    assert any("number 99" in r for r in reasons)
