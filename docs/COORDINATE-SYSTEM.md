# Coordinate System

## Overview

TRITIUM-SC uses a local coordinate system anchored to a real-world geo-reference point. All positions in the battlespace are expressed in local meters with the convention:

- **Origin (0, 0)** = geo-reference point (configurable lat/lng)
- **+X = East**, **+Y = North**, **+Z = Up**
- **1 unit = 1 meter**
- **Heading 0 = North**, clockwise in degrees

The same coordinate math is implemented on both server (`src/engine/tactical/geo.py`) and client (`frontend/js/geo.js`).

## Position Sources

Every `TrackedTarget` carries a `position_source` field identifying how its position was determined, and a `position_confidence` value (0.0 = no confidence, 1.0 = high).

| Source | Description | Confidence | Notes |
|--------|-------------|------------|-------|
| `gps` | Real GPS receiver (robot telemetry via MQTT) | 0.5 - 0.9 | Depends on fix quality (HDOP) |
| `simulation` | Simulation engine places the target | 1.0 | Perfect -- positions are deterministic |
| `mqtt` | Position reported by MQTT-connected device | 0.3 - 0.8 | Depends on device's own positioning |
| `fixed` | Manually configured static position | 0.7 | Cameras, turrets, fixed sensors |
| `yolo` | YOLO detection projected to ground plane | 0.1 | Requires camera calibration for accuracy |
| `unknown` | Source not determined | 0.0 | Default for manually created targets |

## Transform Pipeline

### Simulation Targets (source=simulation, confidence=1.0)
```
SimulationEngine (10Hz tick)
  -> SimulationTarget.to_dict()     # {position: {x, y}, heading, ...}
  -> TargetTracker.update_from_simulation()
  -> TrackedTarget(position_source="simulation", position_confidence=1.0)
```

### YOLO Detections (source=yolo, confidence=0.1)
```
Camera frame
  -> YOLO inference               # bbox, class, confidence
  -> center_x, center_y (0.0-1.0 normalized)
  -> TargetTracker.update_from_detection()
  -> TrackedTarget(position_source="yolo", position_confidence=0.1)
```

To improve YOLO position accuracy, use camera calibration to project pixel coordinates to the ground plane:

```
Detection (cx, cy)
  -> camera_pixel_to_ground(cx, cy, calib)
  -> (x, y) in local meters
```

### GPS/MQTT Targets (source=gps or mqtt)
```
Robot MQTT telemetry
  -> {lat, lng} or {x, y}
  -> latlng_to_local() if lat/lng provided
  -> TargetTracker position update
  -> TrackedTarget(position_source="gps", position_confidence=<varies>)
```

## CameraCalibration

The `CameraCalibration` dataclass holds the parameters needed to project camera pixel coordinates to ground-plane positions.

### Parameters

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `position` | `tuple[float, float]` | required | Camera (x, y) in local meters |
| `heading` | `float` | required | Camera facing direction (degrees, 0=North, clockwise) |
| `fov_h` | `float` | 60.0 | Horizontal field of view in degrees |
| `mount_height` | `float` | 2.5 | Height above ground in meters |
| `max_range` | `float` | 30.0 | Maximum useful detection range in meters |

### Ground-Plane Projection Model

The `camera_pixel_to_ground()` function uses a simplified projection:

1. **Horizontal angle**: The detection's horizontal position (0.0=left, 1.0=right) maps to an angular offset from the camera heading, scaled by the horizontal FOV.

2. **Range estimate**: The detection's vertical position (0.0=top/far, 1.0=bottom/close) maps to a range estimate between 2m (bottom of frame) and `2 + max_range` meters (top of frame).

3. **Ground projection**: The bearing and range are used to compute a ground-plane offset from the camera position using standard trigonometry.

4. **Rejection**: Detections near the top of the frame (cy < 0.1) are rejected as they likely correspond to sky or distant objects that cannot be reliably projected.

```
camera_pixel_to_ground(cx, cy, calib) -> (x, y) | None

  angle_h = (cx - 0.5) * fov_h
  bearing = heading + angle_h

  if cy < 0.1: return None  # above horizon

  range = 2.0 + (1.0 - cy) * max_range

  dx = range * sin(bearing_rad)
  dy = range * cos(bearing_rad)

  return (camera_x + dx, camera_y + dy)
```

### Example Usage

```python
from amy.tactical.geo import CameraCalibration, camera_pixel_to_ground

# Camera on south fence, facing north
calib = CameraCalibration(
    position=(0.0, -15.0),   # 15m south of center
    heading=0.0,              # facing north
    fov_h=90.0,              # wide-angle lens
    mount_height=3.0,
    max_range=25.0,
)

# Detection at center-bottom of frame (close, straight ahead)
pos = camera_pixel_to_ground(0.5, 0.9, calib)
# -> (0.0, -13.0)  approximately 2m north of camera

# Detection at upper-right of frame (far, to the right)
pos = camera_pixel_to_ground(0.8, 0.3, calib)
# -> (x, y) offset to the east and north

# Detection at top of frame (sky/horizon -- rejected)
pos = camera_pixel_to_ground(0.5, 0.05, calib)
# -> None
```

### Database Storage

Camera calibration parameters are stored as nullable columns on the `Camera` model in `src/app/models.py`:

- `position_x` (Float, nullable) -- local X coordinate in meters
- `position_y` (Float, nullable) -- local Y coordinate in meters
- `heading` (Float, nullable) -- facing direction in degrees
- `fov` (Float, nullable) -- horizontal FOV in degrees
- `mount_height` (Float, nullable) -- height above ground in meters

To construct a `CameraCalibration` from a database `Camera` row:

```python
from amy.tactical.geo import CameraCalibration

if camera.position_x is not None and camera.position_y is not None:
    calib = CameraCalibration(
        position=(camera.position_x, camera.position_y),
        heading=camera.heading or 0.0,
        fov_h=camera.fov or 60.0,
        mount_height=camera.mount_height or 2.5,
    )
```

## Known Limitations

1. **Flat ground assumption**: The projection assumes a flat ground plane. Terrain elevation changes will introduce error proportional to the height difference.

2. **No lens distortion correction**: Wide-angle lenses introduce barrel distortion. The linear FOV mapping is most accurate for narrow FOV cameras or near the center of wide-angle frames.

3. **Vertical position as range proxy**: Using `cy` as a range estimator is a rough heuristic. True range would require stereo vision, depth sensors, or known object sizes.

4. **Accuracy degrades with distance**: Objects at the far end of the frame (small cy) have larger position uncertainty. The +/-5m accuracy estimate applies to the 10-30m range bracket.

5. **No camera tilt modeling**: The model assumes the camera is looking roughly horizontal. Strongly tilted cameras (e.g., looking straight down) would need a different projection model.
