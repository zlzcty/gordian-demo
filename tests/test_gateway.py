import json

from gordian.llm.gateway import anthropic_to_openai, openai_to_anthropic, StreamTranslator


def test_request_translation_tools_and_results():
    body = {"system": "s", "max_tokens": 10, "stream": False,
            "messages": [{"role": "user", "content": "hi"},
                         {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]},
                         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "out"}]}],
            "tools": [{"name": "Bash", "description": "d", "input_schema": {"type": "object"}}]}
    out = anthropic_to_openai(body, "m")
    assert out["messages"][0] == {"role": "system", "content": "s"}
    assert out["messages"][2]["tool_calls"][0]["function"]["arguments"] == json.dumps({"command": "ls"})
    assert out["messages"][3] == {"role": "tool", "tool_call_id": "t1", "content": "out"}
    assert out["tools"][0]["function"]["name"] == "Bash"


def test_response_translation_tool_call():
    resp = {"choices": [{"message": {"content": None, "tool_calls": [{"id": "c1", "function": {"name": "Read", "arguments": "{\"p\": 1}"}}]},
                         "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 3, "completion_tokens": 4}}
    out = openai_to_anthropic(resp, "m")
    assert out["stop_reason"] == "tool_use"
    assert out["content"][0] == {"type": "tool_use", "id": "c1", "name": "Read", "input": {"p": 1}}
    assert out["usage"] == {"input_tokens": 3, "output_tokens": 4}


def test_stream_translation_event_order():
    tr = StreamTranslator("m")
    ev = tr.chunk({"choices": [{"delta": {"content": "he"}}]})
    ev += tr.chunk({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "Bash", "arguments": "{\"c"}}]}}]})
    ev += tr.chunk({"choices": [{"delta": {}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 1, "completion_tokens": 2}})
    ev += tr.finish_stream()
    names = [l.split("event: ")[1] for l in ev.splitlines() if l.startswith("event: ")]
    assert names == ["message_start", "content_block_start", "content_block_delta", "content_block_stop",
                     "content_block_start", "content_block_delta", "content_block_stop", "message_delta", "message_stop"]
    assert '"stop_reason": "tool_use"' in ev
