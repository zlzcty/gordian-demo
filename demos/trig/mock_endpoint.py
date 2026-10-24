"""Local, labeled rehearsal endpoint. No provider calls or real credentials."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from wsgiref.simple_server import make_server


def completion_app(response: str):
    def respond(environ, start_response):
        if environ["REQUEST_METHOD"] == "GET" and environ["PATH_INFO"] == "/v1/models":
            start_response("200 OK", [("Content-Type", "application/json")])
            return [json.dumps(dict(object="list", data=[dict(
                id="rehearsal-mock", object="model", created=0, owned_by="local-mock")])).encode()]
        if environ["REQUEST_METHOD"] != "POST" or environ["PATH_INFO"] != "/v1/chat/completions":
            start_response("404 Not Found", [("Content-Type", "text/plain")])
            return [b"Use POST /v1/chat/completions\n"]
        size = int(environ.get("CONTENT_LENGTH") or 0)
        request = json.loads(environ["wsgi.input"].read(size))
        if request.get("model") != "rehearsal-mock":
            start_response("400 Bad Request", [("Content-Type", "application/json")])
            return [b'{"error":{"message":"Only rehearsal-mock is supported"}}']
        body = json.dumps(dict(
            id="mock-rehearsal", object="chat.completion", created=0, model="rehearsal-mock",
            choices=[dict(index=0, finish_reason="stop", message=dict(role="assistant", content=response))],
            usage=dict(prompt_tokens=0, completion_tokens=0, total_tokens=0))).encode()
        start_response("200 OK", [("Content-Type", "application/json"),
                                  ("X-Gordian-Rehearsal", "prewritten-mock")])
        return [body]
    return respond


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8047)
    args = parser.parse_args(argv)
    response = Path(__file__).with_name("mock-response.md").read_text()
    with make_server("127.0.0.1", args.port, completion_app(response)) as server:
        print(f"MOCK ONLY: http://127.0.0.1:{server.server_port}/v1 — model rehearsal-mock", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
