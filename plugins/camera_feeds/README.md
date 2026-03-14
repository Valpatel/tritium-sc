# Camera Feeds Plugin

Unified multi-source camera management for TRITIUM-SC.

## Source Types

| Type | Description | URI Format |
|------|-------------|------------|
| `synthetic` | Procedural video_gen renderers | N/A (uses `extra.scene_type`) |
| `mqtt` | JPEG frames from MQTT topics | `tritium/{device_id}/camera` |
| `rtsp` | RTSP stream via OpenCV | `rtsp://host:port/path` |
| `mjpeg` | MJPEG HTTP stream | `http://host:port/stream` |
| `usb` | USB camera via OpenCV | Device index (e.g. `0`) |

## Data Flow

```
 ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
 │  Synthetic   │     │  RTSP/MJPEG  │     │  MQTT Topic  │
 │  Renderer    │     │  Stream      │     │  Subscriber  │
 └──────┬───────┘     └──────┬───────┘     └──────┬───────┘
        │                    │                    │
        ▼                    ▼                    ▼
 ┌─────────────────────────────────────────────────────────┐
 │              CameraFeedsPlugin                          │
 │  register_source() / remove_source() / list_sources()   │
 │  get_frame(source_id) → BGR numpy array                 │
 └──────────────────────────┬──────────────────────────────┘
                            │
                            ▼
 ┌─────────────────────────────────────────────────────────┐
 │              REST API (/api/camera-feeds/*)              │
 │  GET  /sources           — list all sources              │
 │  POST /sources           — add a new source              │
 │  GET  /sources/{id}      — get source info               │
 │  DEL  /sources/{id}      — remove a source               │
 │  GET  /sources/{id}/snapshot — single JPEG frame         │
 │  GET  /sources/{id}/mjpeg    — MJPEG streaming           │
 │  GET  /sources/types     — list available source types   │
 └─────────────────────────────────────────────────────────┘
```

## Usage

### Add a synthetic camera
```bash
curl -X POST http://localhost:8000/api/camera-feeds/sources \
  -H 'Content-Type: application/json' \
  -d '{"source_id": "syn-1", "source_type": "synthetic", "extra": {"scene_type": "bird_eye"}}'
```

### Add an MQTT camera (edge device)
```bash
curl -X POST http://localhost:8000/api/camera-feeds/sources \
  -H 'Content-Type: application/json' \
  -d '{"source_id": "edge-cam-1", "source_type": "mqtt", "uri": "tritium/edge-01/camera"}'
```

### Stream MJPEG
```html
<img src="/api/camera-feeds/sources/syn-1/mjpeg" />
```

## Plugin Capabilities

`{"data_source", "routes", "ui", "bridge"}`
