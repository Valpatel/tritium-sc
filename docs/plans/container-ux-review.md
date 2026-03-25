# Container & Addon UX Review

**Status:** REVIEWED — agent research complete, restructuring applied
**Date:** 2026-03-23

## User Feedback (Direct Quotes)

> "Simulation should have our mission modes and game should be renamed simulation throughout"
> "We had our old simulation launch UI with LLM generated scenarios, that should be under simulation"
> "All of our tanks and combat units etc should be available in simulation"
> "Tactical and fleet seem like they should be merged? Because fleet would really be our robots and sensors"
> "Intelligence should be Intel which would include detailed target histories"

## Current vs Proposed Container Structure

### Current (8 containers + 2 uncategorized)

| Container | Items | Problem |
|-----------|-------|---------|
| Tactical | 17 panels: ops, units, alerts, missions, patrol, zones... | Too many items, overlaps with Fleet |
| Intelligence | 21 panels: search, dossiers, graph, heatmap... | Name too long, missing "Intel" feel |
| Sensing | 14 panels: cameras, RF, SDR, radar... | Good separation |
| Communications | 8 panels + 10 addon stubs | Good — clear purpose |
| Commander | Amy, graphlings | Correct — swappable commander slot |
| Fleet | 9 panels: devices, assets, edge... | Overlaps with Tactical — fleet ARE tactical units |
| Simulation | 5 panels: city sim, game, replay, scenarios | "Game" should BE simulation, not separate |
| Map & GIS | 6 panels | No container — should it have one? |
| Collaboration | 4 panels | Small — merge into System? |
| System | 10 panels: health, deploy, testing... | Fine |

### Proposed (7 containers)

| Container | New Name | Tabs | Justification |
|-----------|----------|------|---------------|
| **OPERATIONS** | Merge Tactical + Fleet | Units, Alerts, Missions, Patrol, Zones, Fleet Dashboard, Devices, Assets, Edge Diag, Swarm | Operators think in terms of "what's deployed and what's happening" — not "is this a fleet thing or a tactical thing" |
| **INTEL** | Rename Intelligence | Search, Dossiers, Targets, Timeline, Graph, Heatmap, Behavioral, Fusion, Activity Feed | "Intel" is what military/security users say. Target histories, signal analysis, correlation — all intel. |
| **SENSING** | Keep | Cameras, Edge Tracker, RF Motion, WiFi, Radar, SDR, Acoustic, Indoor Pos, ADS-B | Pure data collection — what's detecting what |
| **COMMS** | Keep | Overview + Meshtastic, TAK, Telegram, Slack, Signal, Discord, Matrix, IRC, SMS, Satellite, Email, Webhooks | All communication channels. Clear purpose. |
| **COMMANDER** | Keep | Active Commander (Amy/Sentinel/etc), Thoughts, Voice, Graphlings | The AI brain. Swappable personality. |
| **SIMULATION** | Expand | Battle (was "Game"), City Sim, Scenarios (LLM-generated), Replay, Combat Units, Mission Editor | Everything training/exercise related. The 10-wave battle, city sim, LLM scenarios, unit spawning. |
| **SYSTEM** | Merge + Collaboration | Health, Deploy, Config, Testing, Security, Events, Operators, Map Share | Admin/ops stuff. Collaboration fits here. |

### Changes Summary

1. **Tactical + Fleet → OPERATIONS** — operators don't think about the distinction
2. **Intelligence → INTEL** — shorter, more natural
3. **Game → Battle tab inside SIMULATION** — "game" is confusing, it's a combat exercise
4. **Map & GIS** — becomes part of the map itself (layer controls), not a container
5. **Collaboration → absorbed into SYSTEM** — too small for its own container

### Communication Addon Justifications

| Addon | Real-World Scenario | Makes Sense? |
|-------|-------------------|--------------|
| **Telegram** | Field operators with phones get instant alerts. Low-bandwidth regions. | YES — huge user base, bot API is simple |
| **Slack** | Operations center team coordination. Alert channels for shifts. | YES — standard enterprise comms |
| **Signal** | Sensitive operations requiring E2E encryption. Off-record comms. | YES — high-security requirement |
| **Discord** | Community monitoring, volunteer coordination, public-facing channels. | MAYBE — more consumer than ops |
| **Matrix** | Federated, self-hosted, encrypted. For organizations that won't use commercial services. | YES — government/military preference |
| **IRC** | Extremely low-bandwidth, high-reliability. Works when nothing else does. | YES — fallback comms, amateur radio operators |
| **SMS Gateway** | Alert someone who's offline/no-data. Phone call fallback. | YES — critical alerts need SMS |
| **Satellite** | Beyond line-of-sight operations. Maritime, remote area, disaster response. | YES — niche but essential for some users |
| **Email** | Daily digest reports, audit trail, compliance logging. | YES — everyone has email |
| **Webhooks** | Integration with any external system (PagerDuty, IFTTT, custom). | YES — universal glue |

All 10 make sense. Discord is the weakest — more consumer-oriented — but still valid for community ops.

### WiFi CSI / RuView Integration

**Architecture:**
- **tritium-edge (Tritium-OS):** RuView runs on edge devices (ESP32/RPi with WiFi). New HAL: `hal_wifi_csi.cpp` collects CSI data, runs presence detection, publishes via MQTT `tritium/{device}/csi/detection`
- **tritium-sc (Command Center):** New SENSING tab "WiFi CSI" displays detections on the map as a layer. Human presence shown as heat zones around WiFi APs. Movement vectors shown as arrows.
- **Integration:** CSI detections → MQTT → SC target tracker → fused with BLE + camera for better human ID

**Where it fits:**
- Edge: `tritium-edge/src/hal/hal_wifi_csi.h` — CSI collection driver
- SC Sensing: `plugins/wifi_csi/` — receives MQTT, creates map layer
- SC Map: "WiFi Presence" layer showing detected humans near APs
- SC Intel: CSI detections correlate with BLE/camera targets for unique ID

**Use case:** "3 humans detected in Building 12 via WiFi CSI — no cameras needed. Movement pattern suggests 2 stationary (office workers) + 1 moving (corridor)."

**What the user sees:** A new map layer toggle "WiFi Presence" that shows colored zones around WiFi APs. Green = no humans, yellow = 1-2, red = 3+. Click a zone to see detection confidence and movement vectors.

**Hardware:** Standard WiFi APs with CSI support (ESP32-S3, Intel AX200/AX210, Qualcomm). No special hardware beyond what's already deployed for WiFi fingerprinting.

## Agent Review Findings (2026-03-24)

### UX Reviewer Confirmed:
- **Tactical + Fleet → Operations**: ✅ DONE — "operators don't think about the distinction"
- **Intelligence → Intel**: ✅ DONE — "every military system uses Intel"
- **Game → Battle**: ✅ DONE — "it's a combat exercise, not a game"
- **Collaboration → System**: ✅ DONE — "no operator opens Collaboration during ops"
- **Commander container needs**: Directives, Decision Log, Cognition tabs. Move Graphlings to Intel.
- **Comms 10 addons**: All justified. SMS, Webhooks, Email, Signal are critical four. IRC weakest but near-zero cost.
- **Sensing separation**: Correct — Sensing is about the sensors, Operations is about what you do with the data.

### RuView WiFi CSI Researcher Found:
- **Phase 1 (RSSI occupancy)**: Zero hardware change, use existing ESP32-S3. New `wifi_csi` plugin.
- **Phase 2 (CSI pose)**: Needs research WiFi NICs (Intel 5300). Through-wall skeletal tracking.
- **Phase 3 (multi-node fusion)**: BLE + CSI + Camera → single target UUID with confidence.
- **Architecture**: Edge HAL `hal_wifi_csi.cpp` → MQTT → SC `wifi_csi` plugin → TargetTracker → map layer
- Full research at: `memory/research_ruview_wifi_csi_integration.md`

## Applied Restructuring

| Before | After | Change |
|--------|-------|--------|
| Tactical (17 items) + Fleet (9 items) | **Operations** (26 items) | Merged |
| Intelligence (21 items) | **Intel** (21 items) | Renamed |
| "GAME STATUS" panel title | **"BATTLE STATUS"** | Renamed |
| AI & Comms category | **Commander** + **Communications** | Split |
| Collaboration (4 items) | Merged into **System** | Absorbed |
| 10 categories | **8 categories** | Reduced |

### Open Questions for User

1. Should "Map & GIS" become tabs in OPERATIONS or stay as map controls?
2. Should SIMULATION include a "Mission Editor" tab for building custom scenarios?
3. Should SENSING have sub-categories (visual, RF, acoustic) or stay flat?
4. The Commander container is mostly Amy right now — should it show something useful when no commander is loaded?
