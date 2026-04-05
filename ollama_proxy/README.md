# Ollama Smart Home Proxy

Small HTTP proxy that translates tool calls into REST calls for the virtual smart home.

<mark>Note:</mark> this must be accessed using localhost if you wish to use the microphone.

## Endpoints

- `POST /tools/smart_home`
- `POST /api/generate`
- `POST /api/speak`

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
- The proxy can call `KITTEN_TTS_URL` (default `http://kitten_tts_service:8110`) for speech.
- The test dashboard is served at `http://localhost:8090/`.
- Health check: `GET /health`.
- Wake word config endpoint: `GET /api/wake_word_config`.
- Ollama context size override: `OLLAMA_CONTEXT_SIZE` (default `8192`) via `options.num_ctx`.
- Hide tool metadata in `/api/generate`: `HIDE_TOOL_CALL_RESULTS` (default `false`).

## Wake Word

The dashboard supports wake-word voice control using browser Speech Recognition.

- Defaults: `hey home`, `ok home`
- `WAKE_WORDS` environment variable accepts comma-separated wake words
- `WAKE_COMMAND_TIMEOUT_MS` controls how long the listener waits for a command after wake word

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
