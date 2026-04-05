# DeepFace Data Directory

This folder is mounted into `deepface_service` at `/data/deepface`.

## Configure enrollment images

Place face images under:

- `people/<person_name>/*.jpg`

Example:

- `people/alice/face_01.jpg`
- `people/alice/face_02.jpg`
- `people/bob/face_01.jpg`

## Configure access policy

Edit `access.yaml` to define what each person can do.

Supported protected action names:

- `unlock_door`
- `open_garage`
- `set_thermostat`

## Audit log

Authorization decisions are appended to `auth.log`:

- person (if recognized)
- action requested
- accepted/rejected
