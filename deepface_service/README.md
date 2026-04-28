# DeepFace Auth Service

Local face-recognition authorization service used by `ollama_proxy`.

## GPU acceleration

The service image is built on TensorFlow GPU runtime and expects an NVIDIA GPU host with
NVIDIA Container Toolkit enabled. In Compose, `deepface_service` requests GPU devices via
`gpus: all`.

## Data layout

The service reads from `DEEPFACE_DATA_DIR` (default `/data/deepface`):

- `access.yaml` person-to-action policy
- `people/<person_name>/*.jpg` enrollment images
- `auth.log` append-only authorization decisions

## Optional MySQL persistence

If the following environment variables are all set, the service connects to MySQL on startup,
creates the required tables when they do not already exist, and imports the filesystem-backed
default enrollment data into the database:

- `DEEPFACE_MYSQL_HOST`
- `DEEPFACE_MYSQL_PORT` default `3306`
- `DEEPFACE_MYSQL_DATABASE`
- `DEEPFACE_MYSQL_USER`
- `DEEPFACE_MYSQL_PASSWORD`

Created tables:

- `tblUsers` with `username`, `key`, and `userID` (`uuidv4` stored as `CHAR(36)`)
- `tblFaces` with `faceData`, `faceID`, `faceName`, and `userID`
- `tblAuthLogs` with `timestamp`, `userID`, and `person identification`
- `tblAccessRules` with DB-backed equivalents of `access.yaml` actions

When MySQL is enabled, the service ensures a default user exists with:

- `userID`: `66bbc3cd-6ad8-49d6-875b-74c16b3ddeb3`
- `username`: `default`
- `key`: `a2ecd759be6bd340af29413cc7808f40f5884d2746ddba04d97c4b9fbe0a76ab`

Authorization events continue to be written to `auth.log`. When MySQL is enabled:

- auth requests must include `auth_key`
- the key selects the DB user and the face blobs used for recognition
- access control comes from `tblAccessRules`
- each authorization event is inserted into `tblAuthLogs`

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
  "frame_jpeg_base64": "...",
  "auth_key": "a2ecd759be6bd340af29413cc7808f40f5884d2746ddba04d97c4b9fbe0a76ab"
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
