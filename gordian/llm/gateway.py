"""Minimal Anthropic-Messages-API gateway in front of an OpenAI-compatible endpoint.

Claude Code only speaks the Anthropic Messages API.  To run Claude Code with a
model served through an OpenAI-compatible API (DeepSeek, lab proxies, vLLM,
OpenRouter), this gateway listens on 127.0.0.1 and translates:

    POST /v1/messages               -> POST {api_base}/chat/completions
    POST /v1/messages/count_tokens  -> local estimate

Text, system prompts, tool definitions, tool_use / tool_result blocks and
streaming (SSE) are translated in both directions.  Thinking / effort fields
are dropped (the upstream model reasons on its own).  Nothing but the gateway
process ever holds the upstream API key.  Each request/response pair and the
upstream token usage are written as JSON under ``--output``.

Run standalone:

    python -m gordian.llm.gateway --api-base https://api.deepseek.com/v1 \
        --api-key-env DEEPSEEK_API_KEY --model deepseek-chat --output /tmp/gw

or programmatically through ``Gateway.start()`` (used by ``factory.py``).
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib import error, request

DROP_FIELDS = ("thinking", "effort", "output_config", "metadata", "betas", "fallbacks", "context_management",
               "service_tier", "top_k", "cache_control", "inference_geo", "speed")


# ----------------------------------------------------------------------------- request translation
def _content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif block.get("type") == "tool_result":
            parts.append(_content_to_text(block.get("content", "")))
        elif block.get("type") == "image":
            parts.append("[image omitted]")
    return "\n".join(parts)


def anthropic_to_openai(body: dict, upstream_model: str) -> dict:
    messages = []
    system = body.get("system")
    if system:
        messages.append({"role": "system", "content": _content_to_text(system)})
    for msg in body.get("messages", []):
        role, content = msg.get("role"), msg.get("content")
        if role == "system":
            messages.append({"role": "system", "content": _content_to_text(content)})
            continue
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue
        if role == "user":
            text_parts, tool_results = [], []
            for block in content or []:
                if block.get("type") == "tool_result":
                    tool_results.append({"role": "tool", "tool_call_id": block.get("tool_use_id"),
                                         "content": _content_to_text(block.get("content", "")) or "(no output)"})
                elif block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            # tool results must directly follow the assistant tool_calls message
            messages.extend(tool_results)
            if text_parts:
                messages.append({"role": "user", "content": "\n".join(text_parts)})
        elif role == "assistant":
            text_parts, tool_calls = [], []
            for block in content or []:
                t = block.get("type")
                if t == "text":
                    text_parts.append(block.get("text", ""))
                elif t == "tool_use":
                    tool_calls.append({"id": block.get("id"), "type": "function",
                                       "function": {"name": block.get("name"),
                                                    "arguments": json.dumps(block.get("input") or {})}})
                # thinking / redacted_thinking blocks are dropped
            m = {"role": "assistant", "content": "\n".join(text_parts) or None}
            if tool_calls:
                m["tool_calls"] = tool_calls
            if m["content"] is None and not tool_calls:
                continue
            messages.append(m)
    out = {"model": upstream_model, "messages": messages, "stream": bool(body.get("stream"))}
    if body.get("max_tokens"):
        out["max_tokens"] = int(body["max_tokens"])
    if body.get("temperature") is not None:
        out["temperature"] = body["temperature"]
    if body.get("stop_sequences"):
        out["stop"] = body["stop_sequences"]
    tools = body.get("tools") or []
    oa_tools = []
    for t in tools:
        if "input_schema" not in t:
            continue  # server-side tools (web search etc.) are not supported upstream
        oa_tools.append({"type": "function", "function": {
            "name": t["name"], "description": t.get("description", ""), "parameters": t.get("input_schema")}})
    if oa_tools:
        out["tools"] = oa_tools
        tc = body.get("tool_choice") or {}
        if tc.get("type") == "any":
            out["tool_choice"] = "required"
        elif tc.get("type") == "tool":
            out["tool_choice"] = {"type": "function", "function": {"name": tc.get("name")}}
        elif tc.get("type") == "none":
            out["tool_choice"] = "none"
    if out["stream"]:
        out["stream_options"] = {"include_usage": True}
    return out


# ----------------------------------------------------------------------------- response translation
def _finish_to_stop(reason: Optional[str]) -> str:
    return {"tool_calls": "tool_use", "function_call": "tool_use", "length": "max_tokens",
            "stop": "end_turn"}.get(reason or "stop", "end_turn")


def openai_to_anthropic(resp: dict, model: str) -> dict:
    choice = (resp.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = []
    if msg.get("content"):
        content.append({"type": "text", "text": msg["content"]})
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {"_raw": fn.get("arguments")}
        content.append({"type": "tool_use", "id": tc.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
                        "name": fn.get("name"), "input": args})
    usage = resp.get("usage") or {}
    return {"id": f"msg_{uuid.uuid4().hex[:24]}", "type": "message", "role": "assistant", "model": model,
            "content": content, "stop_reason": _finish_to_stop(choice.get("finish_reason")), "stop_sequence": None,
            "usage": {"input_tokens": int(usage.get("prompt_tokens") or 0),
                      "output_tokens": int(usage.get("completion_tokens") or 0)}}


class StreamTranslator:
    """Turns OpenAI chat-completion chunks into Anthropic SSE events."""

    def __init__(self, model: str):
        self.model = model
        self.msg_id = f"msg_{uuid.uuid4().hex[:24]}"
        self.next_index = 0
        self.text_index: Optional[int] = None
        self.tool_blocks: dict[int, int] = {}      # openai tool index -> anthropic block index
        self.tool_args: dict[int, str] = {}
        self.open_blocks: list[int] = []
        self.finish: Optional[str] = None
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self.started = False

    @staticmethod
    def _ev(name: str, data: dict) -> str:
        return f"event: {name}\ndata: {json.dumps(data)}\n\n"

    def start(self) -> str:
        self.started = True
        return self._ev("message_start", {"type": "message_start", "message": {
            "id": self.msg_id, "type": "message", "role": "assistant", "model": self.model, "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}}})

    def _open(self, block: dict) -> str:
        idx = self.next_index
        self.next_index += 1
        self.open_blocks.append(idx)
        return idx, self._ev("content_block_start", {"type": "content_block_start", "index": idx, "content_block": block})

    def _close(self, idx: int) -> str:
        if idx in self.open_blocks:
            self.open_blocks.remove(idx)
        return self._ev("content_block_stop", {"type": "content_block_stop", "index": idx})

    def chunk(self, data: dict) -> str:
        out = ""
        if not self.started:
            out += self.start()
        usage = data.get("usage")
        if usage:
            self.usage = {"input_tokens": int(usage.get("prompt_tokens") or 0),
                          "output_tokens": int(usage.get("completion_tokens") or 0)}
        for choice in data.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                if self.text_index is None:
                    self.text_index, ev = self._open({"type": "text", "text": ""})
                    out += ev
                out += self._ev("content_block_delta", {"type": "content_block_delta", "index": self.text_index,
                                                        "delta": {"type": "text_delta", "text": delta["content"]}})
            for tc in delta.get("tool_calls") or []:
                i = int(tc.get("index", 0))
                if i not in self.tool_blocks:
                    if self.text_index is not None:
                        out += self._close(self.text_index)
                        self.text_index = None
                    fn = tc.get("function") or {}
                    idx, ev = self._open({"type": "tool_use", "id": tc.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
                                          "name": fn.get("name") or "", "input": {}})
                    self.tool_blocks[i] = idx
                    self.tool_args[i] = ""
                    out += ev
                args = (tc.get("function") or {}).get("arguments")
                if args:
                    self.tool_args[i] += args
                    out += self._ev("content_block_delta", {"type": "content_block_delta", "index": self.tool_blocks[i],
                                                            "delta": {"type": "input_json_delta", "partial_json": args}})
            if choice.get("finish_reason"):
                self.finish = choice["finish_reason"]
        return out

    def finish_stream(self) -> str:
        out = "" if self.started else self.start()
        for idx in list(self.open_blocks):
            out += self._close(idx)
        out += self._ev("message_delta", {"type": "message_delta",
                                          "delta": {"stop_reason": _finish_to_stop(self.finish), "stop_sequence": None},
                                          "usage": {"output_tokens": self.usage["output_tokens"],
                                                    "input_tokens": self.usage["input_tokens"]}})
        out += self._ev("message_stop", {"type": "message_stop"})
        return out


# ----------------------------------------------------------------------------- server
class Gateway(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, api_base: str, api_key: str, model: str, output: Path, token: str, timeout: float = 900.0):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.output = Path(output)
        self.token = token
        self.timeout_s = timeout
        for sub in ("requests", "responses", "usage"):
            (self.output / sub).mkdir(parents=True, exist_ok=True)
        self._thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        return self.server_port

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "Gateway":
        self._thread = threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
        self._thread.start()
        (self.output / "gateway-ready.json").write_text(json.dumps({"port": self.port, "model": self.model}))
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()

    def claude_env(self) -> dict:
        """Environment overrides that make Claude Code talk to this gateway only."""
        m = self.model
        return {"ANTHROPIC_BASE_URL": self.url, "ANTHROPIC_AUTH_TOKEN": self.token, "ANTHROPIC_API_KEY": "",
                "ANTHROPIC_MODEL": m, "ANTHROPIC_DEFAULT_OPUS_MODEL": m, "ANTHROPIC_DEFAULT_SONNET_MODEL": m,
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": m, "ANTHROPIC_SMALL_FAST_MODEL": m,
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}

    def record(self, kind: str, call_id: str, data) -> None:
        text = json.dumps(data, default=str)
        for secret in (self.api_key, self.token):
            if secret:
                text = text.replace(secret, "[REDACTED]")
        (self.output / kind / f"{call_id}.json").write_text(text)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # silence default access log
        pass

    def _authorized(self) -> bool:
        auth = self.headers.get("Authorization", "").removeprefix("Bearer ").strip() or self.headers.get("x-api-key", "")
        return secrets.compare_digest(auth, self.server.token)

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            self._send_json(200, {"data": [{"id": self.server.model, "type": "model", "display_name": self.server.model}]})
        else:
            self._send_json(404, {"type": "error", "error": {"type": "not_found_error", "message": self.path}})

    def do_POST(self):
        server: Gateway = self.server
        if not self._authorized():
            self._send_json(401, {"type": "error", "error": {"type": "authentication_error", "message": "bad token"}})
            return
        size = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(size)
        path = self.path.split("?")[0]
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, {"type": "error", "error": {"type": "invalid_request_error", "message": "bad json"}})
            return
        if path == "/v1/messages/count_tokens":
            est = max(1, len(json.dumps(body.get("messages", [])) + json.dumps(body.get("system", ""))) // 4)
            self._send_json(200, {"input_tokens": est})
            return
        if path != "/v1/messages":
            self._send_json(404, {"type": "error", "error": {"type": "not_found_error", "message": path}})
            return
        call_id = uuid.uuid4().hex
        for f in DROP_FIELDS:
            body.pop(f, None)
        upstream = anthropic_to_openai(body, server.model)
        server.record("requests", call_id, {"anthropic": body, "openai": upstream})
        req = request.Request(server.api_base + "/chat/completions", data=json.dumps(upstream).encode(),
                              headers={"Content-Type": "application/json", "Authorization": f"Bearer {server.api_key}"})
        try:
            resp = request.urlopen(req, timeout=server.timeout_s)
        except error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:2000]
            server.record("responses", call_id, {"error": exc.code, "detail": detail})
            self._send_json(exc.code if exc.code in (400, 401, 403, 404, 429) else 502,
                            {"type": "error", "error": {"type": "api_error", "message": f"upstream {exc.code}: {detail}"}})
            return
        except Exception as exc:  # noqa: BLE001
            server.record("responses", call_id, {"error": str(exc)})
            self._send_json(502, {"type": "error", "error": {"type": "api_error", "message": f"upstream failure: {exc}"}})
            return
        if upstream["stream"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            tr = StreamTranslator(body.get("model") or server.model)
            self.wfile.write(tr.start().encode()); self.wfile.flush()
            for line in resp:
                line = line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                ev = tr.chunk(chunk)
                if ev:
                    self.wfile.write(ev.encode()); self.wfile.flush()
            self.wfile.write(tr.finish_stream().encode()); self.wfile.flush()
            server.record("usage", call_id, {"model": server.model, "usage": tr.usage})
            server.record("responses", call_id, {"stream": True, "stop": tr.finish, "tool_args": tr.tool_args})
        else:
            data = json.loads(resp.read())
            out = openai_to_anthropic(data, body.get("model") or server.model)
            server.record("responses", call_id, data)
            server.record("usage", call_id, {"model": data.get("model"), "usage": data.get("usage")})
            self._send_json(200, out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--api-base", required=True, help="OpenAI-compatible base URL, e.g. https://api.deepseek.com/v1")
    ap.add_argument("--api-key-env", required=True, help="name of the env var holding the upstream key")
    ap.add_argument("--model", required=True, help="upstream model id")
    ap.add_argument("--output", required=True, help="directory for request/response/usage records")
    ap.add_argument("--token", default=None, help="local bearer token (default: generated, printed)")
    args = ap.parse_args(argv)
    token = args.token or secrets.token_urlsafe(32)
    gw = Gateway(args.api_base, os.environ[args.api_key_env], args.model, Path(args.output), token).start()
    print(json.dumps({"url": gw.url, "token": token, "env": gw.claude_env()}, indent=2))
    sys.stdout.flush()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        gw.stop()


if __name__ == "__main__":
    main()
