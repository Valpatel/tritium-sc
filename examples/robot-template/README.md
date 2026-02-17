# TRITIUM-SC Robot Template

A standalone robot brain that connects to TRITIUM-SC via MQTT. Use this as a
starting point for building real hardware (RC cars, drones, turrets) that
participates in the neighborhood defense simulator.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run in simulated mode (no hardware needed)
python robot.py --simulate

# Run with real GPIO hardware
python robot.py --config config.yaml
```

## Architecture

This robot runs completely independently. It connects to an MQTT broker
(same one TRITIUM-SC connects to) and communicates via standardized topics:

```
PUBLISHES:
  tritium/{site}/robots/{robot_id}/telemetry      Position, battery, speed, heading
  tritium/{site}/robots/{robot_id}/status          State changes (active, idle, etc)
  tritium/{site}/robots/{robot_id}/command/ack     Command acknowledgments

SUBSCRIBES:
  tritium/{site}/robots/{robot_id}/command          Dispatch, patrol, recall orders
```

Amy (the AI Commander in TRITIUM-SC) sees this robot as a friendly unit on her
tactical map. She can dispatch it, assign patrols, and monitor its battery --
exactly like simulated units, but this one is REAL.

## Finding the Broker

The robot needs to reach the same MQTT broker that TRITIUM-SC connects to.
Typical setups:

1. **Same machine**: Use `broker: "localhost"` (default). Install Mosquitto
   on the TRITIUM-SC server: `sudo apt install mosquitto`.
2. **LAN robot**: Set `broker` to the TRITIUM-SC server's IP address.
   Run `hostname -I` on the server to find it.
3. **Multiple sites**: Each site uses a different `site_id`. Robots and
   the server must agree on the same `site_id` value.

The `site_id` in `config.yaml` MUST match `MQTT_SITE_ID` in TRITIUM-SC's
`.env` file (default: `"home"`).

## Command Acknowledgment

When the robot receives a command, it publishes an ACK back to TRITIUM-SC
on `tritium/{site}/robots/{robot_id}/command/ack`:

```json
{
  "command": "dispatch",
  "command_timestamp": "2026-02-16T10:30:00+00:00",
  "status": "accepted",
  "robot_id": "rover-alpha",
  "timestamp": "2026-02-16T10:30:00.123+00:00"
}
```

Status values:
- `"accepted"` — Robot will execute the command
- `"rejected"` — Robot cannot execute (unknown command, low battery, etc)
- `"completed"` — Robot finished executing the command

This closes the loop: Amy sends a dispatch, QoS 1 guarantees broker delivery,
and the ACK confirms the robot actually received and understood the order.

## Configuration

Edit `config.yaml`:

```yaml
robot_id: "rover-alpha"
robot_name: "Rover Alpha"
asset_type: "rover"         # rover, drone, turret
site_id: "home"             # Must match TRITIUM-SC mqtt_site_id
home_position:              # Recall destination
  x: 0
  y: 0

mqtt:
  broker: "192.168.1.100"   # Your MQTT broker (where TRITIUM-SC connects)
  port: 1883
  username: ""
  password: ""

hardware:
  mode: "simulated"         # "simulated" or "gpio"
  # GPIO pins (Raspberry Pi)
  motor_left_forward: 17
  motor_left_backward: 27
  motor_right_forward: 22
  motor_right_backward: 23
  turret_pan_pin: 12        # PWM servo
  turret_tilt_pin: 13       # PWM servo
  trigger_pin: 24           # Nerf trigger relay

telemetry:
  interval: 0.5             # Publish rate in seconds
  battery_pin: null          # ADC pin for voltage divider, null = simulated

camera:
  enabled: false
  device: 0                  # /dev/video0
  yolo_model: "yolov8n.pt"
  detection_interval: 1.0    # seconds between YOLO runs
  publish_frames: false      # Publish JPEG frames via MQTT (bandwidth heavy)
```

## Hardware Wiring (RC Car)

```
Raspberry Pi GPIO -> L298N Motor Driver -> DC Motors
                  -> PCA9685 Servo Board -> Pan/Tilt Servos
                  -> Relay Module -> Nerf Trigger Solenoid
                  -> ADS1115 ADC -> Battery Voltage Divider
```

## Adding Your Own Hardware

1. Create a new file in `hardware/` (e.g., `hardware/my_robot.py`)
2. Implement the `HardwareInterface` from `hardware/base.py`
3. Register it in `hardware/__init__.py`
4. Set `hardware.mode: "my_robot"` in config.yaml

## MQTT Protocol

### Telemetry (published every 0.5s)
```json
{
  "name": "Rover Alpha",
  "asset_type": "rover",
  "position": {"x": 5.2, "y": -3.1},
  "heading": 90.0,
  "speed": 2.1,
  "battery": 0.85,
  "status": "active",
  "turret": {"pan": 0, "tilt": 0},
  "timestamp": "2026-02-16T10:30:00Z"
}
```

### Commands (subscribed)
```json
{"command": "dispatch", "x": 10.0, "y": -5.0}
{"command": "patrol", "waypoints": [{"x": 0, "y": 0}, {"x": 10, "y": 10}]}
{"command": "recall"}
{"command": "turret_aim", "pan": 45.0, "tilt": -10.0}
{"command": "fire"}
{"command": "stop"}
```
