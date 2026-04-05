# DeepFace Auth Service

Local face-recognition authorization service used by `ollama_proxy`.

## Data layout

The service reads from `DEEPFACE_DATA_DIR` (default `/data/deepface`):

- `access.yaml` person-to-action policy
- `people/<person_name>/*.jpg` enrollment images
- `auth.log` append-only authorization decisions

Example `access.yaml`:

```yaml
people:
  alice:
    actions:
      - unlock_door
      - open_garage
      - set_thermostat
  bob:
    actions:
      - set_thermostat
```

## API

- `GET /health`
- `POST /auth/authorize`

Request example:

```json
{
  "desired_action": "unlock_door",
  "frame_jpeg_base64": "..."
}
```

Response example:

```json
{
  "person": "alice",
  "desired_action": "unlock_door",
  "accepted": true,
  "decision": "accepted",
  "reason": "authorized"
}
```
