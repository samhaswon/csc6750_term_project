import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from pathlib import Path

VSHOME_URL = os.environ.get("VSHOME_URL", "http://vshome:8080").rstrip("/")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "functiongemma:latest")
SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    (
        """
        You are the smart home control assistant. You must help with any request to read or
        change device state. You are allowed to toggle, turn on/off, lock/unlock, open/close, and
        adjust device values such as temperature, blinds position, or humidity. Do not refuse
        requests to control appliances or lights.

        You can call the smart home tool by responding with a single JSON object (no extra text).
        Use one of:
        {"action":"list"}
        {"action":"get","id":"device_id"}
        {"action":"update","id":"device_id","state":{...}}

        If you need to change state, respond ONLY with the JSON tool call. Do not ask for the
        desired state if the user already specified it.
        """
    ),
)
STATIC_DIR = Path(__file__).resolve().parent / "static"


def read_json(handler):
    content_length = int(handler.headers.get("Content-Length", 0))
    if content_length <= 0:
        return None, "missing body"
    try:
        payload = handler.rfile.read(content_length)
        return json.loads(payload.decode("utf-8")), None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "invalid json"


def write_json(handler, status, payload):
    response = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(response)))
    handler.end_headers()
    handler.wfile.write(response)


def forward_request(method, path, body=None):
    url = f"{VSHOME_URL}{path}"
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, method=method, data=data, headers=headers)
    try:
        with urlopen(request, timeout=10) as response:
            return response.getcode(), json.loads(response.read().decode("utf-8"))
    except HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def build_system_prompt():
    status, data = forward_request("GET", "/api/devices")
    if status != 200 or not isinstance(data, list):
        return SYSTEM_PROMPT.strip()
    lines = [SYSTEM_PROMPT.strip(), "", "Available devices:"]
    for device in data:
        device_id = device.get("id", "unknown")
        name = device.get("name", "unknown")
        kind = device.get("kind", "unknown")
        room = device.get("room") or "Unassigned"
        state = json.dumps(device.get("state", {}), separators=(",", ":"))
        lines.append(
            f"- {name} (id: {device_id}, kind: {kind}, room: {room}, state: {state})"
        )
    lines.append("")
    lines.append("Respond ONLY with the JSON tool call when acting.")
    return "\n".join(lines)


def call_ollama(prompt):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": build_system_prompt(),
        "stream": False,
    }
    request = Request(
        f"{OLLAMA_URL}/api/generate",
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            status = response.getcode()
            data = json.loads(response.read().decode("utf-8"))
            output = data.get("response", "")
            if output:
                print(f"[ollama] response: {output}")
            else:
                print(f"[ollama] empty response payload: {data}")
            return status, data
    except HTTPError as err:
        data = json.loads(err.read().decode("utf-8"))
        print(f"[ollama] error {err.code}: {data}")
        return err.code, data


def run_with_tool_loop(prompt, max_steps=2):
    status, data = call_ollama(prompt)
    if status != 200:
        return status, data, None, None
    response_text = data.get("response", "")
    tool_call = extract_json_object(response_text)
    if not tool_call:
        return status, data, None, None
    for _ in range(max_steps):
        print(f"[tool] model_call={tool_call}")
        tool_result = execute_tool_call(tool_call)
        follow_up = (
            f"{prompt}\n\nTool call:\n{json.dumps(tool_call)}\n"
            f"Tool result:\n{json.dumps(tool_result)}\n\n"
            "Respond with a final confirmation or another JSON tool call."
        )
        status, data = call_ollama(follow_up)
        if status != 200:
            return status, data, tool_call, tool_result
        response_text = data.get("response", "")
        next_call = extract_json_object(response_text)
        if not next_call:
            return status, data, tool_call, tool_result
        tool_call = next_call
    return status, data, tool_call, tool_result


def pull_model():
    print(f"[ollama] pulling model: {OLLAMA_MODEL}")
    payload = {"name": OLLAMA_MODEL}
    request = Request(
        f"{OLLAMA_URL}/api/pull",
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=120) as response:
            return response.getcode(), json.loads(response.read().decode("utf-8"))
    except HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def should_pull(error_payload):
    if not isinstance(error_payload, dict):
        return False
    message = str(error_payload.get("error", "")).lower()
    return "not found" in message and "model" in message


def extract_json_object(text):
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = text[start : end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        return None


def execute_tool_call(tool_call):
    action = tool_call.get("action")
    if action == "list":
        status, data = forward_request("GET", "/api/devices")
        return {"status": status, "data": data}
    if action == "get":
        device_id = tool_call.get("id")
        if not device_id:
            return {"status": 400, "data": {"error": "missing id"}}
        status, data = forward_request("GET", f"/api/devices/{device_id}")
        return {"status": status, "data": data}
    if action == "update":
        device_id = tool_call.get("id")
        state = tool_call.get("state")
        if not device_id:
            return {"status": 400, "data": {"error": "missing id"}}
        if not isinstance(state, dict) or not state:
            return {"status": 400, "data": {"error": "missing state"}}
        status, data = forward_request("PUT", f"/api/devices/{device_id}", {"state": state})
        return {"status": status, "data": data}
    return {"status": 400, "data": {"error": "unsupported action"}}


def read_static(path):
    if path in ("/", ""):
        path = "/index.html"
    safe_path = (STATIC_DIR / path.lstrip("/")).resolve()
    if STATIC_DIR not in safe_path.parents and safe_path != STATIC_DIR:
        return None, "text/plain"
    if not safe_path.exists() or not safe_path.is_file():
        return None, "text/plain"
    content_type = "text/plain"
    if safe_path.suffix == ".html":
        content_type = "text/html"
    elif safe_path.suffix == ".css":
        content_type = "text/css"
    elif safe_path.suffix == ".js":
        content_type = "application/javascript"
    return safe_path.read_bytes(), content_type


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            write_json(self, 200, {"status": "ok"})
            return
        content, content_type = read_static(self.path)
        if content is None:
            write_json(self, 404, {"error": "not found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        if self.path == "/api/generate":
            payload, error = read_json(self)
            if error:
                write_json(self, 400, {"error": error})
                return
            prompt = payload.get("prompt", "").strip()
            if not prompt:
                write_json(self, 400, {"error": "missing prompt"})
                return
            print(f"[dashboard] prompt: {prompt}")
            status, data, tool_call, tool_result = run_with_tool_loop(prompt)
            if status != 200 and should_pull(data):
                pull_status, pull_data = pull_model()
                if pull_status != 200:
                    write_json(self, pull_status, pull_data)
                    return
                status, data, tool_call, tool_result = run_with_tool_loop(prompt)
            if status != 200:
                write_json(self, status, data)
                return
            response_text = data.get("response", "")
            payload_out = {"response": response_text}
            if tool_call:
                payload_out["tool_call"] = tool_call
            if tool_result:
                payload_out["tool_result"] = tool_result
            write_json(self, 200, payload_out)
            return
        if self.path != "/tools/smart_home":
            write_json(self, 404, {"error": "not found"})
            return
        payload, error = read_json(self)
        if error:
            write_json(self, 400, {"error": error})
            return
        action = payload.get("action")
        print(f"[tool] action={action} payload={payload}")
        if action == "list":
            status, data = forward_request("GET", "/api/devices")
            write_json(self, status, data)
            return
        if action == "get":
            device_id = payload.get("id")
            if not device_id:
                write_json(self, 400, {"error": "missing id"})
                return
            status, data = forward_request("GET", f"/api/devices/{device_id}")
            write_json(self, status, data)
            return
        if action == "update":
            device_id = payload.get("id")
            state = payload.get("state")
            if not device_id:
                write_json(self, 400, {"error": "missing id"})
                return
            if not isinstance(state, dict) or not state:
                write_json(self, 400, {"error": "missing state"})
                return
            status, data = forward_request("PUT", f"/api/devices/{device_id}", {"state": state})
            write_json(self, status, data)
            return
        write_json(self, 400, {"error": "unsupported action"})

    def log_message(self, fmt, *args):
        return


def main():
    port = int(os.environ.get("PORT", "8090"))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"[ollama_proxy] starting server on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
