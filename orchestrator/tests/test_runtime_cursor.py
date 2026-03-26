"""Tests for Cursor CLI runtime helpers."""

from orchestrator.runtime import extract_cursor_final_text


def test_extract_cursor_final_text_prefers_result_field():
    text, payloads = extract_cursor_final_text(
        '{"type":"result","subtype":"success","is_error":false,"result":"cursor done"}'
    )

    assert text == "cursor done"
    assert payloads[0]["type"] == "result"


def test_extract_cursor_final_text_reads_jsonl_stream():
    raw = "\n".join(
        [
            '{"type":"status","message":"thinking"}',
            '{"type":"result","subtype":"success","is_error":false,"result":"final answer"}',
        ]
    )

    text, payloads = extract_cursor_final_text(raw)

    assert text == "final answer"
    assert len(payloads) == 2
