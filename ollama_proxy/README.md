# Ollama Smart Home Proxy

Small HTTP proxy that translates tool calls into REST calls for the virtual smart home.

## Endpoints

- `POST /tools/smart_home`
- `POST /api/generate`

Request body examples:

```json
{ "action": "list" }
```

```json
{ "action": "get", "id": "light_kitchen" }
```

```json
{ "action": "update", "id": "light_kitchen", "state": { "on": true } }
```

Prompt test example:

```json
{ "prompt": "Turn on the kitchen lights." }
```

## Notes

- The proxy forwards to `VSHOME_URL` (default `http://vshome:8080`).
- The proxy can call `DEEPFACE_URL` (default `http://deepface_service:8120`) for protected actions.
- The test dashboard is served at `http://localhost:8090/`.
- Health check: `GET /health`.

## Protected Actions

When `AUTH_ENABLED=true` (default), update requests are authenticated with a webcam frame before
state writes for:

- unlocking doors (`lock` device with `locked=false`)
- opening doors (`doors` device with `open=true`)
- setting thermostat values (`thermostat` with `temperature`)

## Tool-Call Evaluation Harness

Use the unittest harness to compare tool-call success rates across models:

```bash
python3 -m unittest ollama_proxy.tests.test_tool_call_success_rates
```

Optional environment variables:

- `OLLAMA_PROXY_URL` (default: `http://localhost:8090`)
- `TOOL_EVAL_MODELS` comma-separated model list
- `TOOL_EVAL_TIMEOUT` request timeout in seconds (default: `120`)
- `TOOL_EVAL_SKIP=1` to skip the test

The harness writes detailed results to:

`ollama_proxy/tests/artifacts/tool_call_success_rates.json`
