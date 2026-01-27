# Virtual Smart Home

Simple Go + WebSocket dashboard for a virtual smart home. Device inventory and initial state
are driven by `devices.yaml` (the video feed card is static in the frontend).

## Run

```bash
cd vshome
go run .
```

Open `http://localhost:8080`.

## Device configuration

Edit `devices.yaml` to add/change devices. Each device needs a unique `id`, a `name`, and a
`kind`. Initial state lives under `state`.

Supported kinds:
- `toggle`
- `sensor`
- `lock`
- `blind`
- `vacuum`
- `thermostat`
- `humidifier`
- `toaster`
- `doors`

## WebSocket protocol (frontend uses this)

`ws://localhost:8080/ws`

- Server -> client: `{"type":"state","devices":[...]}` initial state
- Server -> client: `{"type":"update","device":{...}}` change notification
- Client -> server: `{"type":"set","id":"device_id","state":{...}}`

The frontend only updates UI after backend messages, so repeated clicks before the state
change are idempotent from the UI perspective.

## External control API (not used by the frontend)

- `GET /api/devices` list all devices and state
- `GET /api/devices/{id}` fetch a single device
- `PUT /api/devices/{id}` update a device state

Example:

```bash
curl -X PUT http://localhost:8080/api/devices/light_kitchen \
  -H "Content-Type: application/json" \
  -d '{"state":{"on":true}}'
```
