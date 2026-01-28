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
        You have access to functions. If you decide to invoke any of the function(s),
        you MUST put it in the format of:
        [func_name(param_name=param_value, param_name2=param_value2), func_name2(param)]
        You SHOULD NOT include any other text in the response if you call a function.

        Available functions:
        [
          {
            "name": "list_devices",
            "description": "List all devices and their state",
            "parameters": {
              "type": "object",
              "properties": {}
            }
          },
          {
            "name": "get_device",
            "description": "Fetch a device by id",
            "parameters": {
              "type": "object",
              "properties": {
                "id": { "type": "string" }
              },
              "required": ["id"]
            }
          },
          {
            "name": "update_device_state",
            "description": "Update device state by id",
            "parameters": {
              "type": "object",
              "properties": {
                "id": { "type": "string" },
                "state": { "type": "object" }
              },
              "required": ["id", "state"]
            }
          }
        ]
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
    # lines.append("Respond ONLY with a tool call when acting.")
    return "\n".join(lines)


def build_full_prompt(user_prompt, tool_result=None):
    prompt_parts = [build_system_prompt(), "", f"User: {user_prompt}"]
    if tool_result is not None:
        prompt_parts.extend(
            [
                "",
                "<start_function_response>",
                json.dumps(tool_result),
                "<end_function_response>",
            ]
        )
    prompt_parts.append("Assistant:")
    return "\n".join(prompt_parts)


def call_ollama(prompt, tool_result=None):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": build_full_prompt(prompt, tool_result),
        "stream": False,
    }
    request = Request(
        f"{OLLAMA_URL}/api/generate",
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=60) as response:
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
    tool_call = extract_function_call(response_text)
    if not tool_call:
        return status, data, None, None
    for _ in range(max_steps):
        print(f"[tool] model_call={tool_call}")
        tool_result = execute_tool_call(tool_call)
        status, data = call_ollama(prompt, tool_result=tool_result)
        if status != 200:
            return status, data, tool_call, tool_result
        response_text = data.get("response", "")
        next_call = extract_function_call(response_text)
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


def extract_function_call(text):
    if not text:
        return None
    tool_payload = _extract_from_bracket_calls(text)
    if tool_payload:
        return tool_payload
    tool_payload = _extract_from_tool_block(text)
    if tool_payload:
        return tool_payload
    tool_payload = _extract_from_inline_call(text)
    if tool_payload:
        return tool_payload
    start_tag = "<start_function_call>"
    end_tag = "<end_function_call>"
    start = text.find(start_tag)
    end = text.find(end_tag)
    if start != -1 and end != -1 and end > start:
        snippet = text[start + len(start_tag) : end].strip()
        payload = _decode_json(snippet)
        if payload:
            return _tool_args_from_payload(payload)
    snippet = _extract_first_json(text)
    if not snippet:
        return None
    payload = _decode_json(snippet)
    if not payload:
        return None
    return _tool_args_from_payload(payload)


def _extract_from_tool_block(text):
    marker = "```tool_call"
    start = text.find(marker)
    if start == -1:
        return None
    end = text.find("```", start + len(marker))
    if end == -1:
        return None
    block = text[start + len(marker) : end].strip()
    snippet = _extract_first_json(block)
    if not snippet:
        return None
    payload = _decode_json(snippet)
    if not payload:
        return None
    return _tool_args_from_payload(payload)


def _extract_from_inline_call(text):
    lower = text.lower()
    if "update_device_state" in lower:
        snippet = _extract_first_json(text)
        if snippet:
            payload = _decode_json(snippet)
            if payload:
                payload["name"] = "update_device_state"
                return _tool_args_from_payload(payload)
    if "get_device" in lower:
        snippet = _extract_first_json(text)
        if snippet:
            payload = _decode_json(snippet)
            if payload:
                payload["name"] = "get_device"
                return _tool_args_from_payload(payload)
    if "list_devices" in lower:
        return {"action": "list"}
    if "smart_home.update" in lower:
        snippet = _extract_first_json(text)
        if snippet:
            payload = _decode_json(snippet)
            if payload:
                payload["name"] = "update_device_state"
                return _tool_args_from_payload(payload)
    return None


def _extract_from_bracket_calls(text):
    stripped = text.strip()
    if not (stripped.startswith("[") and stripped.endswith("]")):
        return None
    inner = stripped[1:-1].strip()
    if not inner:
        return None
    calls = []
    current = []
    depth = 0
    in_string = False
    quote = ""
    for char in inner:
        if char in ("'", "\""):
            if in_string and char == quote:
                in_string = False
                quote = ""
            elif not in_string:
                in_string = True
                quote = char
        if char == "(" and not in_string:
            depth += 1
        elif char == ")" and not in_string:
            depth = max(depth - 1, 0)
        if char == "," and depth == 0 and not in_string:
            calls.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        calls.append("".join(current).strip())
    if not calls:
        return None
    tool_calls = []
    for call in calls:
        parsed = _parse_function_call(call)
        if parsed:
            tool_calls.append(parsed)
    if not tool_calls:
        return None
    return tool_calls[0] if len(tool_calls) == 1 else {"batch": tool_calls}


def _parse_function_call(text):
    if "(" not in text or not text.endswith(")"):
        return None
    name, args = text.split("(", 1)
    name = name.strip()
    args = args[:-1].strip()
    if name == "list_devices":
        return {"action": "list"}
    if name == "get_device":
        params = _parse_params(args)
        return {"action": "get", "id": params.get("id")}
    if name == "update_device_state":
        params = _parse_params(args)
        return {"action": "update", "id": params.get("id"), "state": params.get("state")}
    return None


def _parse_params(text):
    if not text:
        return {}
    params = {}
    parts = []
    current = []
    depth = 0
    in_string = False
    quote = ""
    for char in text:
        if char in ("'", "\""):
            if in_string and char == quote:
                in_string = False
                quote = ""
            elif not in_string:
                in_string = True
                quote = char
        if char == "{" and not in_string:
            depth += 1
        elif char == "}" and not in_string:
            depth = max(depth - 1, 0)
        if char == "," and depth == 0 and not in_string:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current).strip())
    for part in parts:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith("{") and value.endswith("}"):
            parsed = _decode_json(value)
            if parsed is not None:
                params[key] = parsed
                continue
        if value.startswith("\"") and value.endswith("\""):
            params[key] = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            params[key] = value[1:-1]
        else:
            params[key] = value
    return params


def _extract_first_json(text):
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _decode_json(snippet):
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        return None


def _tool_args_from_payload(payload):
    if not isinstance(payload, dict):
        return None
    name = payload.get("name")
    if name == "smart_home":
        return payload.get("arguments") or payload.get("parameters")
    if name == "list_devices":
        return {"action": "list"}
    if name == "get_device":
        args = payload.get("arguments") or payload.get("parameters") or {}
        return {"action": "get", "id": args.get("id")}
    if name == "update_device_state":
        args = payload.get("arguments") or payload.get("parameters") or {}
        return {"action": "update", "id": args.get("id"), "state": args.get("state")}
    if "action" in payload:
        return payload
    return None


def execute_tool_call(tool_call):
    if "batch" in tool_call and isinstance(tool_call["batch"], list):
        results = [execute_tool_call(item) for item in tool_call["batch"]]
        return {"status": 207, "data": results}
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
