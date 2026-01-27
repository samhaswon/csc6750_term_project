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
- The test dashboard is served at `http://localhost:8090/`.
- Health check: `GET /health`.
