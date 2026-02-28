# NPC Intelligence Plugin

## Overview

The NPC Intelligence Plugin (`tritium.npc-intelligence`) adds behavioral AI to neutral NPCs
(pedestrians, vehicles, animals) in the TRITIUM-SC simulation. NPCs react to combat events,
flee from danger, rubberneck at interesting situations, spread panic through crowds, and can
occasionally radicalize into hostiles under extreme conditions.

## Architecture

The plugin follows the External Observer Pattern: it subscribes to `sim_telemetry_batch` on
the EventBus, maintains a parallel registry of `NPCBrain` objects, and mutates NPC behavior
by directly modifying `SimulationTarget` objects. The `SimulationEngine` tick loop is never
modified.

```
PluginManager
     |
     v
NPCIntelligencePlugin (PluginInterface)
     |
     +-- NPCBrainManager              # Manages all NPC brains
     |     +-- NPCBrain[]             # One per NPC
     |     |     +-- StateMachine     # Reuse existing (state_machine.py)
     |     |     +-- NPCPersonality   # Traits dataclass
     |     |     +-- NPCMemory        # Short-term event buffer
     |     +-- LLMThinkScheduler      # Rate limiter + queue
     |     |     +-- ModelRouter      # Reuse existing
     |     |     +-- OllamaFleet      # Reuse existing
     |     +-- BehaviorTreeFallback   # No-LLM fallback
     |
     +-- EventReactor                 # EventBus subscriber
     +-- AllianceManager              # Radicalization logic
     +-- CrowdDynamics                # NPC-to-NPC influence
```

## NPC FSM Definitions

### Civilian Pedestrian (7 states)

States: `walking`, `pausing`, `observing`, `fleeing`, `hiding`, `curious`, `panicking`

| From | To | Condition | Priority |
|------|----|-----------|----------|
| any | fleeing | danger_nearby | 20 |
| fleeing | hiding | cover_available | 10 |
| fleeing | panicking | no cover + close danger | 15 |
| any | curious | interest + high curiosity trait | 5 |
| curious | observing | close enough to interest | 3 |
| pausing | walking | timeout 3-15s | 0 |
| observing | walking | timeout 2-10s | 0 |
| hiding | walking | timeout 5-30s + no danger | 0 |
| panicking | fleeing | timeout 5-15s | 0 |

### Civilian Vehicle (5 states)

States: `driving`, `stopped`, `yielding`, `evading`, `parked`

| From | To | Condition | Priority |
|------|----|-----------|----------|
| any | evading | danger_nearby | 20 |
| driving | stopped | intersection/obstacle | 5 |
| driving | yielding | emergency nearby | 10 |
| driving | parked | high interest + curiosity | 3 |
| stopped | driving | timeout 2-8s | 0 |
| yielding | driving | timeout 3-10s | 0 |
| parked | driving | timeout 10-30s | 0 |

### Animal (5 states)

States: `wandering`, `resting`, `startled`, `fleeing`, `following`

| From | To | Condition | Priority |
|------|----|-----------|----------|
| any | startled | loud noise | 15 |
| startled | fleeing | auto after 1-3s | 0 |
| any | following | dog + person nearby | 5 |
| wandering | resting | timeout 5-20s | 0 |
| resting | wandering | timeout 3-15s | 0 |
| fleeing | wandering | timeout 5-15s + safe | 0 |

## Personality System

Each NPC has 4 traits (0.0-1.0):

- **curiosity**: Tendency to observe/approach events
- **caution**: Tendency to flee/hide (inverse of bravery)
- **sociability**: Influenced by nearby NPC states (crowd dynamics)
- **aggression**: Potential for radicalization (very low for most NPCs)

Defaults by type:
- Pedestrians: curiosity 0.3-0.7, caution 0.3-0.7, sociability 0.4-0.8, aggression 0.0-0.3
- Vehicles: curiosity 0.1-0.3, caution 0.5-0.9, sociability 0.1-0.3, aggression 0.0-0.1
- Animals: curiosity 0.2-0.5, caution 0.6-0.9, sociability 0.1-0.4, aggression 0.0-0.1

## LLM Integration

Think cycle runs every 5-10s per NPC (staggered). Uses `gemma3:4b` via existing
`OllamaFleet` + `ModelRouter`. Max 2 concurrent LLM calls. When Ollama is unavailable,
falls back to weighted-random behavior trees using personality traits.

Prompt includes: name, personality, current state, position, recent events, nearby entities.
Response is a single action word mapped to FSM state.

## Alliance Transitions

Radicalization requires ALL conditions simultaneously:
1. 3+ `target_eliminated` events in NPC memory within 60s
2. Global escalation at amber or red
3. No friendly units within 30m
4. NPC aggression trait > 0.7
5. 120s cooldown since last radicalization

## Performance Budget

- 70+ NPCs at 10Hz tick rate
- Plugin tick < 5ms total
- LLM calls staggered, never blocking the tick loop
- Brain attachment/detachment is O(1)

## Files

| File | Purpose |
|------|---------|
| `src/engine/simulation/npc_intelligence/__init__.py` | Package exports |
| `src/engine/simulation/npc_intelligence/plugin.py` | NPCIntelligencePlugin |
| `src/engine/simulation/npc_intelligence/brain.py` | NPCBrain, NPCPersonality, NPCMemory |
| `src/engine/simulation/npc_intelligence/brain_manager.py` | NPCBrainManager |
| `src/engine/simulation/npc_intelligence/npc_fsm.py` | FSM factories |
| `src/engine/simulation/npc_intelligence/think_scheduler.py` | LLMThinkScheduler |
| `src/engine/simulation/npc_intelligence/prompts.py` | Prompt templates + parser |
| `src/engine/simulation/npc_intelligence/fallback.py` | BehaviorTreeFallback |
| `src/engine/simulation/npc_intelligence/event_reactor.py` | EventReactor |
| `src/engine/simulation/npc_intelligence/alliance.py` | AllianceManager |
| `src/engine/simulation/npc_intelligence/crowd.py` | CrowdDynamics |
