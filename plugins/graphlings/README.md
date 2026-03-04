# Graphlings Plugin for TRITIUM-SC

[Graphlings](https://graphlings.net) — Created by Matthew Valancy, Copyright 2026 Valpatel Software LLC.

Crystal creature AI agents living as NPCs in the TRITIUM-SC simulation world.

## Quick Start

1. Ensure the Graphling home server is running (default: `http://localhost:4774`)
2. Drop the `graphlings/` folder into `tritium-sc/plugins/`
3. The plugin auto-discovers via `graphlings_loader.py`

```bash
# Override server URL if needed
export GRAPHLINGS_SERVER_URL=http://localhost:4774

# Run tests
cd /path/to/tritium-sc
python3 -m pytest plugins/graphlings/tests/ -v
```

## Configuration

Environment variables (all optional):

| Variable | Default | Description |
|----------|---------|-------------|
| `GRAPHLINGS_SERVER_URL` | `http://localhost:4774` | Graphling home server URL |
| `GRAPHLINGS_SERVER_TIMEOUT` | `5.0` | HTTP timeout in seconds |
| `GRAPHLINGS_MAX_AGENTS` | `5` | Max simultaneous graphlings |
| `GRAPHLINGS_THINK_INTERVAL` | `3.0` | Base think interval (seconds) |
| `GRAPHLINGS_PERCEPTION_RADIUS` | `50.0` | How far graphlings can see |

## What Happens During Gameplay

### Automatic Lifecycle

The `SimulationLifecycleHandler` listens for game state changes:

- **Countdown** -- All available graphlings batch-deploy. First gets the drone_operator role (combatant), rest are civilians.
- **Victory / Defeat / Game Over** -- All graphlings batch-recall with the reason logged.
- **Shutdown** -- Plugin stop() recalls any remaining deployments.

### Think Loop

Each deployed graphling runs an adaptive think cycle:

1. **Perceive** -- Scan nearby entities, classify threats, calculate danger
2. **Think** -- Send perception to the Graphling server, get back thought + action + emotion
3. **Act** -- Execute action via MotorOutput (say, move_to, observe, flee, emote)
4. **Remember** -- Buffer experiences, sync to home server periodically

Think intervals adapt to urgency: 0.5s in danger, 10s when idle.

### Personality Effects

Graphling personality traits modify behavior:
- **Caution >= 0.7** -- Think 30% more often
- **Sociability >= 0.7** + friendlies nearby -- Think 40% more often
- **Curiosity >= 0.7** + events pending -- Think 50% more often

## HTTP API

The plugin registers these endpoints:

- `GET /api/graphlings/status` -- Plugin status, deployed count, compute stats
- `POST /api/graphlings/deploy` -- Manual deploy: `{"soul_id": "...", "role_name": "..."}`
- `POST /api/graphlings/{soul_id}/recall` -- Manual recall

## Troubleshooting

**Graphlings don't deploy on countdown:**
- Check server is reachable: `curl http://<server>/deployment/active`
- Check logs for `batch_deploy failed` warnings

**Think cycles timing out:**
- Increase `GRAPHLINGS_SERVER_TIMEOUT`
- Check server load / Ollama status

**No graphlings visible in simulation:**
- Verify spawn_points in config match valid map coordinates
- Check `GET /api/graphlings/status` for deployed count
