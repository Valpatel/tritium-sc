# TAK Integration -- TRITIUM-SC Bidirectional CoT Bridge

## 1. Overview

TRITIUM-SC integrates with the Team Awareness Kit (TAK) ecosystem via
bidirectional Cursor on Target (CoT) XML messaging. Every TRITIUM target --
simulated hostiles, YOLO detections, MQTT robots, camera sensors -- appears
as a real-time icon on ATAK/WinTAK/WebTAK maps. Conversely, ATAK phone users
connected to the same TAK server appear as tracked targets in TRITIUM's
tactical map and are visible to Amy's sensorium.

The integration uses [pytak](https://github.com/snstac/pytak), the standard
Python TAK client library, to speak CoT XML over TCP or TLS to any
TAK server (OpenTAKServer, FreeTAKServer, TAK Server official).

### Architecture

```
                         TRITIUM-SC                         TAK Network
  +-------------------------------------------------+    +-------------------+
  |                                                 |    |                   |
  |  SimulationEngine ---+                          |    |  OpenTAKServer    |
  |  TargetTracker ------+                          |    |  (8088 TCP)       |
  |  YOLO detections ----+--> TAKBridge             |    |  (8089 TLS)       |
  |  MQTT robots --------+    |                     |    |  (8443 WebTAK)    |
  |                           |  _publish_loop      |    |                   |
  |                           |  every N seconds     |    |                   |
  |                           +------ CoT XML ------+------>  TAK Server     |
  |                           |                     |    |       |           |
  |                           |  _handle_inbound    |    |       v           |
  |  TargetTracker <----------+<----- CoT XML ------+----+  ATAK phones     |
  |  EventBus <-- tak_client_update                 |    |  WinTAK stations  |
  |  Amy sensorium <-- tak feed                     |    |  WebTAK browser   |
  |  WebSocket --> browser                          |    |                   |
  |                                                 |    +-------------------+
  +-------------------------------------------------+
                                                          +-------------------+
  Meshtastic Bridge (optional)                            |                   |
  +-------------------+                                   |  LoRa Mesh        |
  | MeshtasticBridge  +--- position --> TargetTracker     |  (off-grid nodes) |
  | (serial/TCP)      |                      |            |                   |
  +-------------------+                      v            +-------------------+
                                        TAKBridge
                                     (publishes all)
```

### Files

| File | Purpose |
|------|---------|
| `src/engine/comms/cot.py` | Pure CoT XML generation/parsing (zero external deps) |
| `src/engine/comms/tak_bridge.py` | TAKBridge class (pytak + EventBus integration) |
| `src/app/routers/tak.py` | FastAPI `/api/tak/*` endpoints |
| `src/app/config.py` | TAK settings (environment variables) |

---

## 2. Quick Start

### Step 1: Install OpenTAKServer

```bash
curl -s -L https://i.opentakserver.io/ubuntu_installer | bash -
```

Default ports after installation:
- **8088** -- TCP CoT (unencrypted)
- **8089** -- TLS CoT (encrypted)
- **8443** -- WebTAK UI

See: https://github.com/brian7704/OpenTAKServer

### Step 2: Install pytak

```bash
.venv/bin/pip install pytak
```

pytak is a pure Python library -- no compiled dependencies. It provides the
TCP/TLS transport and asyncio worker framework for sending and receiving
CoT XML.

### Step 3: Configure TRITIUM

Add to your `.env`:

```bash
TAK_ENABLED=true
TAK_COT_URL=tcp://localhost:8088
TAK_CALLSIGN=TRITIUM-SC
TAK_TEAM=Cyan
TAK_ROLE=HQ
```

### Step 4: Start TRITIUM

```bash
./start.sh
```

The TAK bridge starts automatically during the app lifespan when
`TAK_ENABLED=true` and pytak is importable. Check the server logs for:

```
INFO amy.tak: TAK bridge started (tcp://localhost:8088)
INFO amy.tak: TAK connected to tcp://localhost:8088
```

### Step 5: Verify

```bash
# Check bridge status
curl http://localhost:8000/api/tak/status
```

Expected response:

```json
{
  "enabled": true,
  "connected": true,
  "cot_url": "tcp://localhost:8088",
  "callsign": "TRITIUM-SC",
  "team": "Cyan",
  "role": "HQ",
  "messages_sent": 42,
  "messages_received": 3,
  "clients": 1,
  "last_error": "",
  "tx_queue_size": 0
}
```

### Step 6: Open WebTAK

Navigate to `https://localhost:8443` in your browser. TRITIUM targets should
appear as icons on the map. The TRITIUM command post itself appears as a
blue C2 marker with the configured callsign.

Connect an ATAK phone to the same server -- the phone user will appear as a
tracked target in TRITIUM's War Room.

---

## 3. Configuration Reference

All TAK settings are environment variables loaded via Pydantic in
`src/app/config.py`. Set them in `.env` or export them in the shell.

### Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `TAK_ENABLED` | `false` | Enable the TAK bridge. When false, no pytak threads start. |
| `TAK_COT_URL` | `tcp://localhost:8088` | TAK server CoT endpoint. Use `tcp://` for plaintext, `ssl://` for TLS. |
| `TAK_CALLSIGN` | `TRITIUM-SC` | How TRITIUM appears on TAK maps. This is the SA (situational awareness) marker. |
| `TAK_TEAM` | `Cyan` | Team color on TAK maps. Options: Cyan, Red, White, Yellow, Blue, Green, Orange, Maroon, Purple, Dark Blue, Teal. |
| `TAK_ROLE` | `HQ` | Team role. Options: HQ, Team Member, Team Lead, Sniper, Forward Observer, RTO, K9. |
| `TAK_PUBLISH_INTERVAL` | `5.0` | Seconds between target broadcast cycles. Lower = more responsive but more traffic. |
| `TAK_STALE_SECONDS` | `120` | Seconds until a published CoT position report goes stale. ATAK grays out stale icons. |

### TLS Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `TAK_TLS_CLIENT_CERT` | _(empty)_ | Path to TLS client certificate (PEM). Required when `TAK_COT_URL` uses `ssl://`. |
| `TAK_TLS_CLIENT_KEY` | _(empty)_ | Path to TLS client private key (PEM). |
| `TAK_TLS_CA_CERT` | _(empty)_ | Path to CA certificate (PEM) for verifying the TAK server. |

### Future Settings (planned)

| Variable | Default | Description |
|----------|---------|-------------|
| `TAK_GEOCHAT_ENABLED` | `true` | Enable GeoChat message relay between TRITIUM and TAK. |
| `TAK_HISTORY_ENABLED` | `true` | Enable CoT message history storage for after-action review. |
| `TAK_HISTORY_RETENTION_DAYS` | `30` | Days to retain CoT history before automatic cleanup. |
| `TAK_SENSORIUM_ENABLED` | `true` | Feed TAK events into Amy's sensorium as awareness inputs. |
| `TAK_ESCALATION_ENABLED` | `true` | Allow inbound TAK hostile markers to trigger escalation. |

---

## 4. CoT Type Mapping

CoT type codes follow MIL-STD-2525B symbology. The format is
`a-{affiliation}-{dimension}-{function}` where:

- `a` = atom (a single entity)
- Affiliation: `f`=friend, `h`=hostile, `n`=neutral, `u`=unknown
- Dimension: `G`=ground, `A`=air, `S`=surface
- Function codes identify the specific entity type

### Specific Type Codes

| TRITIUM Asset Type | Alliance | CoT Type | MIL-STD-2525B Description |
|--------------------|----------|----------|---------------------------|
| `rover` | friendly | `a-f-G-E-V` | Friend ground equipment vehicle |
| `drone` | friendly | `a-f-A-M-H` | Friend air rotary wing (helicopter) |
| `turret` | friendly | `a-f-G-I-E` | Friend ground infrastructure equipment |
| `camera` | friendly | `a-f-G-E-S` | Friend ground equipment sensor |
| `tank` | friendly | `a-f-G-E-V` | Friend ground equipment vehicle (heavy) |
| `apc` | friendly | `a-f-G-E-V` | Friend ground equipment vehicle (APC) |
| `person` | hostile | `a-h-G-U-C-I` | Hostile ground unit combat infantry |
| `rover` | hostile | `a-h-G-E-V` | Hostile ground equipment vehicle |
| `drone` | hostile | `a-h-A-M-H` | Hostile air rotary wing |
| `person` | neutral | `a-n-G-U-C` | Neutral ground unit civilian |
| `vehicle` | neutral | `a-n-G-E-V` | Neutral ground equipment vehicle |

### Alliance Fallbacks

When the specific `(asset_type, alliance)` pair is not found, the system
falls back to generic codes:

| Alliance | Fallback Code | Description |
|----------|---------------|-------------|
| friendly | `a-f-G` | Friend ground (generic) |
| hostile | `a-h-G` | Hostile ground (generic) |
| neutral | `a-n-G` | Neutral ground (generic) |
| unknown | `a-u-G` | Unknown ground (generic) |

### TRITIUM SA Marker

TRITIUM itself broadcasts its position as `a-f-G-E-C-I` (Friend ground
equipment C2 infrastructure) using the `make_sa_cot()` function. This
appears as a command post icon on TAK maps.

### "How" Codes (Source Attribution)

The `how` attribute in CoT XML indicates how the position was determined:

| TRITIUM Source | How Code | Meaning |
|----------------|----------|---------|
| `simulation` | `m-s` | Machine-simulated |
| `yolo` | `m-r` | Machine-reported (sensor) |
| `mqtt` | `m-g` | Machine-GPS derived |
| `manual` | `h-e` | Human-estimated |
| TRITIUM SA | `h-g-i-g-o` | Human-GPS-inertial-GPS-other |

### Team Colors

Each alliance maps to a TAK team color for map display:

| Alliance | Team Color |
|----------|-----------|
| friendly | Cyan |
| hostile | Red |
| neutral | White |
| unknown | Yellow |

---

## 5. API Reference

All endpoints are defined in `src/app/routers/tak.py` under the
`/api/tak` prefix.

### GET /api/tak/status

Returns bridge connection status and operational statistics.

**Request:**
```bash
curl http://localhost:8000/api/tak/status
```

**Response (bridge enabled and connected):**
```json
{
  "enabled": true,
  "connected": true,
  "cot_url": "tcp://localhost:8088",
  "callsign": "TRITIUM-SC",
  "team": "Cyan",
  "role": "HQ",
  "messages_sent": 156,
  "messages_received": 12,
  "clients": 2,
  "last_error": "",
  "tx_queue_size": 0
}
```

**Response (bridge disabled):**
```json
{
  "enabled": false,
  "connected": false,
  "error": "TAK bridge not configured"
}
```

### GET /api/tak/clients

Returns all discovered TAK clients (ATAK phones, WinTAK stations) that have
sent CoT position reports through the TAK server.

**Request:**
```bash
curl http://localhost:8000/api/tak/clients
```

**Response:**
```json
{
  "clients": [
    {
      "uid": "ANDROID-abc123",
      "callsign": "ALPHA-1",
      "lat": 37.7749,
      "lng": -122.4194,
      "alt": 16.0,
      "alliance": "friendly",
      "asset_type": "person",
      "speed": 1.2,
      "heading": 45.0,
      "last_seen": 1740009600.0
    }
  ],
  "count": 1
}
```

**Error (bridge unavailable):**
```json
{
  "error": "TAK bridge not available"
}
```
Status code: 503

### POST /api/tak/send

Send a raw CoT XML string to the TAK server. The XML is queued for
transmission -- it does not block until sent.

**Request:**
```bash
curl -X POST http://localhost:8000/api/tak/send \
  -H "Content-Type: application/json" \
  -d '{"cot_xml": "<event version=\"2.0\" uid=\"test-1\" type=\"a-f-G\" how=\"m-s\" time=\"2026-02-22T00:00:00Z\" start=\"2026-02-22T00:00:00Z\" stale=\"2026-02-22T00:02:00Z\"><point lat=\"37.7749\" lon=\"-122.4194\" hae=\"16.0\" ce=\"10.0\" le=\"10.0\"/><detail/></event>"}'
```

**Response:**
```json
{
  "status": "queued"
}
```

### POST /api/tak/alert

Send a threat alert marker to the TAK server. Creates a hostile infantry
marker (`a-h-G-U-C-I`) at the given coordinates with a 5-minute stale time.

**Request:**
```bash
curl -X POST http://localhost:8000/api/tak/alert \
  -H "Content-Type: application/json" \
  -d '{
    "callsign": "CONTACT-NORTH",
    "lat": 37.7752,
    "lng": -122.4190,
    "alt": 16.0,
    "remarks": "Two individuals approaching north fence"
  }'
```

**Response:**
```json
{
  "status": "sent",
  "callsign": "CONTACT-NORTH"
}
```

The `remarks` field is optional. When provided, it appears in the remarks
section of the CoT detail element, visible in ATAK's marker info panel.

### POST /api/tak/chat (planned)

Send a GeoChat message to the TAK network.

**Request:**
```bash
curl -X POST http://localhost:8000/api/tak/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "All units hold position",
    "to": "All Chat Rooms"
  }'
```

**Response:**
```json
{
  "status": "sent"
}
```

### GET /api/tak/chat/messages (planned)

Retrieve recent GeoChat messages.

**Request:**
```bash
curl http://localhost:8000/api/tak/chat/messages?limit=50
```

### GET /api/tak/history (planned)

Retrieve historical CoT messages for after-action review.

**Request:**
```bash
curl "http://localhost:8000/api/tak/history?start=2026-02-22T00:00:00Z&end=2026-02-22T12:00:00Z"
```

---

## 6. GeoChat

GeoChat is TAK's built-in messaging system. Messages are transmitted as CoT
XML events with type `b-t-f` (bits-text-freetext) and a `__chat` detail
element.

### CoT Format

```xml
<event version="2.0" uid="GeoChat.TRITIUM-SC.All Chat Rooms.12345"
       type="b-t-f" how="h-g-i-g-o"
       time="2026-02-22T10:00:00Z" start="2026-02-22T10:00:00Z"
       stale="2026-02-23T10:00:00Z">
  <point lat="37.7749" lon="-122.4194" hae="16.0" ce="10.0" le="10.0"/>
  <detail>
    <__chat parent="RootContactGroup" groupOwner="false"
            chatroom="All Chat Rooms" id="All Chat Rooms"
            senderCallsign="TRITIUM-SC">
      <chatgrp uid0="TRITIUM-SC-SA" uid1="All Chat Rooms" id="All Chat Rooms"/>
    </__chat>
    <link uid="TRITIUM-SC-SA" type="a-f-G-E-C-I" relation="p-p"/>
    <remarks source="BAO.F.ATAK.TRITIUM-SC"
             to="All Chat Rooms"
             time="2026-02-22T10:00:00Z">
      All units hold position
    </remarks>
  </detail>
</event>
```

### Message Routing

```
ATAK user types message
  --> CoT XML via TAK server
    --> TAKBridge._handle_inbound()
      --> Detect b-t-f type
        --> Parse __chat / remarks
          --> EventBus.publish("tak_geochat", {...})
            --> WebSocket bridge --> browser Chat panel
            --> Amy sensorium (if TAK_SENSORIUM_ENABLED)
```

### Configuration

- `TAK_GEOCHAT_ENABLED` (planned) -- enables chat relay. When disabled,
  GeoChat CoT events are received but not forwarded to the EventBus.
- Chat messages appear in the Command Center's Chat panel alongside Amy's
  conversation.

---

## 7. Meshtastic Bridge

When both the Meshtastic bridge and TAK bridge are enabled, off-grid LoRa
mesh nodes automatically appear on TAK maps. No additional configuration is
required beyond enabling both bridges.

### Data Flow

```
LoRa Radio (off-grid)
  --> Meshtastic serial/TCP
    --> MeshtasticBridge
      --> TargetTracker.update_from_simulation()
        --> TAKBridge._publish_loop()
          --> target_to_cot_xml()
            --> TAK Server
              --> ATAK phones see LoRa nodes on their maps
```

### CoT Enrichment

When a target originates from Meshtastic, the CoT remarks include mesh
radio metadata:

```
health:100/100 kills:0 status:active mesh:snr=12.5,rssi=-65,hops=2
```

This lets ATAK operators see signal quality and hop count for mesh nodes
directly in the marker info panel.

### How It Works

The Meshtastic bridge and TAK bridge do not communicate directly. Instead,
they both interact through the shared `TargetTracker`:

1. MeshtasticBridge receives position from a LoRa node
2. MeshtasticBridge injects it into TargetTracker via `update_from_simulation()`
3. TAKBridge's `_publish_loop()` reads all targets from TargetTracker
4. Meshtastic-origin targets get `how="m-g"` (machine-GPS derived)
5. TAK server distributes the CoT to all connected clients

The TAKBridge skips targets whose `target_id` starts with `tak_` to prevent
echo loops, but Meshtastic targets use a `mesh_` prefix, so they are always
published.

---

## 8. Escalation Integration

TAK integration feeds into TRITIUM's threat escalation pipeline. When a
hostile marker arrives from an ATAK user (e.g., a field team member marking
a suspicious person), it can trigger automated responses.

### Inbound Threat Flow

```
ATAK user places hostile marker
  --> CoT XML type a-h-G-U-C-I
    --> TAKBridge._handle_inbound()
      --> TargetTracker (alliance="hostile")
        --> ThreatClassifier (2Hz scan)
          --> AutoDispatcher
            --> Nearest friendly unit dispatched
              --> Amy announces threat
```

### EventBus Events

| Event | Payload | Trigger |
|-------|---------|---------|
| `tak_client_update` | `{uid, target_id, callsign, alliance, lat, lng}` | Any inbound CoT from a TAK client |
| `tak_threat_marker` (planned) | `{uid, callsign, lat, lng, remarks, source_uid}` | Inbound CoT with hostile affiliation |

### How TAK Feeds Escalation

1. The `ThreatClassifier` (in `src/engine/tactical/escalation.py`) scans the
   TargetTracker at 2Hz for hostile targets.
2. TAK-originated hostiles appear in the tracker with `source="tak"` and
   `alliance="hostile"`.
3. The classifier does not distinguish between TAK hostiles and
   simulation/YOLO hostiles -- all hostiles are threats.
4. When a new hostile appears, the `AutoDispatcher` selects the nearest
   available friendly unit and dispatches it.
5. Amy's thinking thread sees the hostile in her battlespace summary and
   can issue additional commands or commentary.

### Guard Against False Markers

TAK-originated hostile markers are tagged with `source="tak"` in the
TargetTracker. Amy's sensorium can weight these differently from
machine-detected hostiles (YOLO) since they are human-reported and may
have different confidence levels.

---

## 9. Amy Integration

TAK events feed into Amy's cognitive pipeline through the sensorium, giving
her awareness of TAK network activity alongside camera feeds, simulation
state, and MQTT robot telemetry.

### Sensorium Feed

The sensorium (`src/amy/brain/sensorium.py`) receives TAK data through the
EventBus. Each TAK event is tagged with a source label and importance level:

| Source Label | Event | Importance | Description |
|--------------|-------|------------|-------------|
| `tak` | `tak_client_update` | 0.4 | Generic TAK client position update |
| `tak_position` | `tak_client_update` | 0.3 | Known friendly position (routine) |
| `tak_chat` | `tak_geochat` | 0.6 | GeoChat message from TAK network |
| `tak_threat` | `tak_threat_marker` | 0.9 | Hostile marker from TAK operator |

### How TAK Appears in Amy's Narrative

Amy's temporal narrative (generated every thinking cycle) includes TAK
data when it is relevant:

```
[10:32:15] TAK client ALPHA-1 repositioned to north gate (37.7752, -122.4190)
[10:32:18] TAK GeoChat from BRAVO-2: "Contact spotted near parking lot"
[10:32:20] TAK hostile marker placed by ALPHA-1 at (37.7753, -122.4188)
```

Amy processes these events alongside her other inputs. A TAK hostile marker
at importance 0.9 will likely trigger a deliberation cycle (L4 thinking),
while routine position updates at 0.3 contribute to situational awareness
without demanding attention.

### Amy's TAK Actions

Amy can also publish to the TAK network through her motor programs:

- **Alert**: Place a hostile marker via `POST /api/tak/alert`
- **Chat**: Send a GeoChat message to ATAK operators (planned)
- **Dispatch**: When Amy dispatches a unit, the unit's new waypoint appears
  as an updated position on TAK maps

---

## 10. TLS Setup

For production deployments, use TLS (port 8089) to encrypt CoT traffic.

### Option A: OpenTAKServer Admin Panel

1. Open `https://your-tak-server:8443/admin`
2. Navigate to Certificate Management
3. Generate a new client certificate for TRITIUM
4. Download the certificate package (PEM format)
5. Extract to a secure directory on the TRITIUM server

### Option B: Manual Certificate Generation

Generate a CA and client certificate with OpenSSL:

```bash
# Create CA key and certificate
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 \
  -out ca.pem -subj "/CN=TRITIUM-TAK-CA"

# Create client key and CSR
openssl genrsa -out client.key 2048
openssl req -new -key client.key -out client.csr \
  -subj "/CN=TRITIUM-SC"

# Sign client certificate with CA
openssl x509 -req -in client.csr -CA ca.pem -CAkey ca.key \
  -CAcreateserial -out client.pem -days 365 -sha256
```

Import `ca.pem` into OpenTAKServer's trusted certificates.

### Configure TRITIUM

```bash
TAK_COT_URL=ssl://tak-server.local:8089
TAK_TLS_CLIENT_CERT=/etc/tritium/certs/client.pem
TAK_TLS_CLIENT_KEY=/etc/tritium/certs/client.key
TAK_TLS_CA_CERT=/etc/tritium/certs/ca.pem
```

The bridge passes these paths to pytak, which configures the SSL context:

```python
# In tak_bridge.py _pytak_main():
config["PYTAK_TLS_CLIENT_CERT"] = self._tls_client_cert
config["PYTAK_TLS_CLIENT_KEY"] = self._tls_client_key
config["PYTAK_TLS_CLIENT_CAFILE"] = self._tls_ca_cert
```

### Verify TLS Connection

```bash
# Test connectivity directly
openssl s_client -connect tak-server.local:8089 \
  -cert client.pem -key client.key -CAfile ca.pem

# Check TRITIUM bridge status
curl http://localhost:8000/api/tak/status
# Should show "connected": true with ssl:// URL
```

### Troubleshooting TLS

| Symptom | Cause | Fix |
|---------|-------|-----|
| `SSL: CERTIFICATE_VERIFY_FAILED` | CA certificate not trusted | Ensure `TAK_TLS_CA_CERT` points to the correct CA |
| `SSL: TLSV1_ALERT_UNKNOWN_CA` | Server does not trust client CA | Import your CA into OpenTAKServer's truststore |
| `SSL handshake failed` | Certificate/key mismatch | Verify cert and key match: `openssl x509 -noout -modulus -in client.pem` vs `openssl rsa -noout -modulus -in client.key` |
| Connection timeout on 8089 | Firewall blocking TLS port | Check `ufw status` or `iptables -L` |
| `last_error: "pytak not installed"` | Missing dependency | Run `.venv/bin/pip install pytak` |

---

## 11. Troubleshooting

### "pytak not installed"

The bridge requires pytak but does not list it as a hard dependency (it is
optional). Install it:

```bash
.venv/bin/pip install pytak
```

If pytak is not installed, the bridge logs a warning and disables itself.
The rest of TRITIUM operates normally.

### Connected but no icons on ATAK

1. **Check the TAK server is reachable:**
   ```bash
   nc -zv localhost 8088
   ```
2. **Check the CoT URL matches the server's binding:**
   - OpenTAKServer binds to `0.0.0.0:8088` by default
   - If connecting from another machine, use the server's IP, not `localhost`
3. **Check the firewall:**
   ```bash
   sudo ufw allow 8088/tcp
   ```
4. **Verify ATAK is connected to the same server:**
   - In ATAK: Settings > Network Preferences > TAK Server > verify the address
5. **Check publish interval:**
   - Default is 5 seconds. New targets may take one cycle to appear.
   - Lower `TAK_PUBLISH_INTERVAL` for faster updates.

### TAK clients appear then disappear

The `TAK_STALE_SECONDS` value controls how long a position report is valid.
If ATAK phones publish infrequently (e.g., every 60s) but stale is set to
30s, positions will flicker.

Fix: set `TAK_STALE_SECONDS` to at least 2x the longest expected publish
interval of connected clients.

### Queue filling up

Check `tx_queue_size` in the status response. If it is consistently near
500 (the queue max), the TAK server is unreachable or too slow.

```bash
curl http://localhost:8000/api/tak/status | jq .tx_queue_size
```

Causes:
- TAK server is down
- Network partition between TRITIUM and TAK server
- TLS handshake is stuck (check certificates)

When the queue fills, the oldest messages are dropped to make room for
fresh ones. This is by design -- stale position reports are useless.

### GeoChat messages not arriving (planned)

1. Verify `TAK_GEOCHAT_ENABLED=true`
2. Check that ATAK is sending to "All Chat Rooms" (not a private channel)
3. Check EventBus for `tak_geochat` events
4. Check WebSocket connection in the browser console

### Bridge shows connected but messages_sent stays at 0

The publish loop only sends when `self._connected` is True AND
`TargetTracker.get_all()` returns targets. If the simulation is not running
and no YOLO/MQTT targets exist, there is nothing to publish.

Start a simulation or spawn a target:
```bash
curl -X POST http://localhost:8000/api/amy/simulation/spawn \
  -H "Content-Type: application/json" \
  -d '{"alliance": "hostile", "asset_type": "person"}'
```

---

## 12. Operator Guide

### Field Team Setup

Each ATAK phone user on your team should:

1. Install ATAK from the Play Store or TAK.gov
2. Connect to the same TAK server TRITIUM uses
3. Set a unique callsign (e.g., ALPHA-1, BRAVO-2)
4. Set team color to match their role

### Callsign Conventions

| Callsign Pattern | Role |
|-----------------|------|
| `TRITIUM-SC` | Command post (automated) |
| `ALPHA-{n}` | Perimeter team |
| `BRAVO-{n}` | Response team |
| `CHARLIE-{n}` | Observation posts |
| `ROVER-{name}` | Robotic assets (automated) |
| `DRONE-{name}` | Aerial assets (automated) |

### Team Color Assignments

| Team | Color | Purpose |
|------|-------|---------|
| Command | Cyan | TRITIUM system, commanders |
| Red Team | Red | Opposing force (exercise) |
| Blue Team | Blue | Defending force |
| Observers | White | Non-combatants, referees |
| Unassigned | Yellow | New connections, unknown |

### Field Deployment Checklist

- [ ] OpenTAKServer running and accessible from the field
- [ ] TRITIUM `TAK_ENABLED=true` and bridge shows `connected: true`
- [ ] All ATAK phones connected to the TAK server
- [ ] Callsigns assigned and confirmed on the map
- [ ] Team colors set correctly
- [ ] Communication check: send a GeoChat message from each phone
- [ ] Verify TRITIUM targets appear on ATAK maps
- [ ] Verify ATAK users appear in TRITIUM's tactical map
- [ ] If using TLS: all certificates distributed and tested
- [ ] If using Meshtastic: LoRa radios powered on and meshed

### Radio Procedures

When using voice radio alongside TAK:

- TAK handles position and text -- use radio for time-critical voice comms
- Reference TAK callsigns on voice: "ALPHA-1, this is TRITIUM, dispatch to
  marker CONTACT-NORTH"
- Amy's TTS announcements use TAK callsigns when addressing specific units
- Log all voice comms in GeoChat for after-action review

---

## 13. After-Action Review

### CoT History (planned)

The TAK bridge can store all inbound and outbound CoT messages for
post-event analysis. Enable with `TAK_HISTORY_ENABLED=true`.

### Retrieving History

```bash
# All messages in a time range
curl "http://localhost:8000/api/tak/history?start=2026-02-22T08:00:00Z&end=2026-02-22T12:00:00Z"
```

**Response:**
```json
{
  "messages": [
    {
      "timestamp": "2026-02-22T08:15:32Z",
      "direction": "outbound",
      "uid": "sim-hostile-1",
      "type": "a-h-G-U-C-I",
      "callsign": "Hostile-1",
      "lat": 37.7751,
      "lng": -122.4192,
      "raw_xml": "<event ...>...</event>"
    },
    {
      "timestamp": "2026-02-22T08:15:33Z",
      "direction": "inbound",
      "uid": "ANDROID-abc123",
      "type": "a-f-G-U-C",
      "callsign": "ALPHA-1",
      "lat": 37.7749,
      "lng": -122.4194,
      "raw_xml": "<event ...>...</event>"
    }
  ],
  "count": 2
}
```

### Export Format

History data is stored as JSONL (one JSON object per line) in
`data/tak/history/YYYY-MM-DD.jsonl`. Each line contains:

```json
{
  "ts": "2026-02-22T08:15:32.123Z",
  "dir": "out",
  "uid": "sim-hostile-1",
  "type": "a-h-G-U-C-I",
  "callsign": "Hostile-1",
  "lat": 37.7751,
  "lng": -122.4192,
  "xml": "<event ...>...</event>"
}
```

### Replay

Export history and feed it into a TAK server for replay:

```bash
# Export a session's CoT messages
curl "http://localhost:8000/api/tak/history?start=2026-02-22T08:00:00Z&end=2026-02-22T12:00:00Z&format=cot" > session.xml

# Replay via pytak
python -m pytak -U tcp://localhost:8088 < session.xml
```

---

## 14. Architecture Deep Dive

### Threading Model

The TAK bridge uses three threads:

```
Main Thread (FastAPI)
  |
  +-- tak-pytak (daemon thread)
  |     asyncio event loop
  |     pytak CLITool.run()
  |       +-- _TritiumCoTSender.run()   (async worker)
  |       +-- _TritiumCoTReceiver.run() (async worker)
  |
  +-- tak-publish (daemon thread)
        _publish_loop()
        sleeps TAK_PUBLISH_INTERVAL between cycles
        reads TargetTracker.get_all()
        queues CoT XML into _tx_queue
```

**Thread 1: `tak-pytak`** -- Runs pytak's asyncio event loop. pytak
requires its own event loop (it uses `CLITool` which manages async workers).
This thread is created with `asyncio.new_event_loop()` to avoid conflicts
with FastAPI's event loop.

**Thread 2: `tak-publish`** -- A simple polling loop that reads all targets
from the `TargetTracker` every `TAK_PUBLISH_INTERVAL` seconds, converts them
to CoT XML, and puts them into the `_tx_queue`. Also publishes TRITIUM's own
SA position.

**Thread 3: Main thread** -- FastAPI handles HTTP requests to `/api/tak/*`
endpoints. These read bridge state (`.stats`, `.clients`) or queue messages
(`.send_cot()`).

### Thread-to-Async Bridge

The `_tx_queue` is a standard `queue.Queue` (thread-safe). The async
`_TritiumCoTSender` polls it with `get_nowait()` in a 100ms loop:

```python
# In _TritiumCoTSender.run():
try:
    xml_bytes = self._bridge_tx.get_nowait()
    await self._pytak_tx.put(xml_bytes)
except queue.Empty:
    await asyncio.sleep(0.1)
```

The `_TritiumCoTReceiver` reads from pytak's async rx_queue and calls
`bridge._handle_inbound()` directly. `_handle_inbound()` calls
`EventBus.publish()` and `TargetTracker.update_from_simulation()`, both
of which are thread-safe.

### Queue Management

The outbound queue (`_tx_queue`) has a hard limit of 500 messages. When
the queue is full, the oldest message is dropped to make room:

```python
def send_cot(self, xml_string: str) -> None:
    try:
        self._tx_queue.put_nowait(xml_string)
    except queue.Full:
        try:
            self._tx_queue.get_nowait()  # Drop oldest
        except queue.Empty:
            pass
        try:
            self._tx_queue.put_nowait(xml_string)
        except queue.Full:
            pass
```

This prevents memory growth when the TAK server is unreachable. Dropping
old position reports is acceptable because stale positions are useless --
only the latest position matters.

### EventBus Events

| Event | Published When | Payload |
|-------|---------------|---------|
| `tak_connected` | pytak connects to TAK server | `{cot_url, callsign}` |
| `tak_disconnected` | pytak loses connection | `{cot_url}` |
| `tak_client_update` | Inbound CoT from any TAK client | `{uid, target_id, callsign, alliance, lat, lng}` |
| `tak_geochat` (planned) | Inbound GeoChat message | `{sender, message, chatroom, timestamp}` |
| `tak_threat_marker` (planned) | Inbound hostile CoT | `{uid, callsign, lat, lng, remarks}` |

### Echo Loop Prevention

When TRITIUM publishes a target to the TAK server, the server may echo it
back to all subscribers (including TRITIUM). To prevent infinite loops:

1. All TAK-originated targets get their `target_id` prefixed with `tak_`
2. The `_should_publish()` filter skips any target with a `tak_` prefix
3. Result: TRITIUM targets flow out, TAK targets flow in, neither echoes

### Reconnection Behavior

pytak uses its own internal reconnection logic within the asyncio event
loop. If the TAK server becomes unreachable:

1. pytak's send/receive coroutines raise an exception
2. `_pytak_main()` catches it, sets `_connected = False`
3. `tak_disconnected` event fires on the EventBus
4. The `tak-pytak` thread exits, `_loop.close()` is called
5. The `_publish_loop` continues running but skips publishing (checks
   `self._connected`)

To reconnect, the bridge must be stopped and started again (manual
restart), or the application must be restarted. Automatic reconnection
with exponential backoff is a planned improvement.

### Graceful Degradation

The bridge is designed to degrade gracefully at every level:

| Condition | Behavior |
|-----------|----------|
| pytak not installed | Warning logged, bridge disabled, app continues |
| TAK server unreachable | `connected=False`, publish loop pauses, queued messages dropped |
| Malformed inbound CoT | Logged, skipped, bridge continues |
| Queue full (500 messages) | Oldest dropped, newest accepted |
| TLS certificate error | Connection fails, `last_error` updated, app continues |
| TargetTracker empty | No CoT published, SA position still sent |

### Performance Characteristics

| Metric | Value |
|--------|-------|
| Publish cycle overhead | ~2ms per 50 targets (XML serialization) |
| Inbound parse time | ~0.1ms per CoT message (XML parse + dict build) |
| Queue capacity | 500 messages (~50KB at ~100 bytes/message) |
| Thread count | 2 daemon threads (pytak + publish) |
| Memory footprint | ~5MB (pytak + queue + client registry) |
| Network bandwidth (50 targets, 5s interval) | ~5 KB/s outbound |

---

## Test Coverage

| Test File | Tests | What |
|-----------|-------|------|
| `tests/amy/core/test_cot.py` | CoT XML generation/parsing | `target_to_cot_xml`, `cot_xml_to_target`, `make_sa_cot`, type mapping, round-trip |
| `tests/amy/core/test_tak_bridge.py` | TAKBridge unit tests | Init, start/stop, publish filter, inbound handling, queue management, echo prevention |
| `tests/amy/core/test_tak_e2e.py` | Integration tests | Full pipeline with real EventBus + TargetTracker, mock pytak |
| `tests/amy/api/test_tak_router.py` | API endpoint tests | `/api/tak/status`, `/clients`, `/send`, `/alert` |
