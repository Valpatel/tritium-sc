#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Hostile Agent -- standalone LLM-driven hostile for TRITIUM-SC.

Each instance is one hostile combatant that connects via MQTT and
uses a local LLM (Ollama) to make tactical decisions.

Usage:
    python main.py --hostile-id hostile-01 --mqtt-host localhost \
        --start-x 100 --start-y 0 --model qwen2.5:7b

    python main.py --hostile-id hostile-02 --start-x 120 --start-y 10 \
        --model llama3.2:3b --decision-interval 3
"""

import argparse
import signal
import time
import sys

from hostile import HostileAgent
from mqtt_client import HostileMQTTClient
from llm_client import LLMClient


def main():
    parser = argparse.ArgumentParser(description="TRITIUM hostile agent with LLM brain")
    parser.add_argument("--hostile-id", default="hostile-01")
    parser.add_argument("--name", default="")
    parser.add_argument("--mqtt-host", default="localhost")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--site", default="home")
    parser.add_argument("--start-x", type=float, default=100.0)
    parser.add_argument("--start-y", type=float, default=0.0)
    parser.add_argument("--target-x", type=float, default=0.0)
    parser.add_argument("--target-y", type=float, default=0.0)
    parser.add_argument("--speed", type=float, default=1.5)
    parser.add_argument("--health", type=int, default=100)
    parser.add_argument("--model", default="qwen2.5:7b")
    parser.add_argument("--ollama-host", default="http://localhost:11434")
    parser.add_argument("--decision-interval", type=float, default=5.0)
    parser.add_argument("--tick-rate", type=float, default=10.0, help="Ticks per second")
    args = parser.parse_args()

    # Create agent
    agent = HostileAgent(
        hostile_id=args.hostile_id,
        start_x=args.start_x,
        start_y=args.start_y,
        speed=args.speed,
        health=args.health,
        name=args.name,
    )
    agent.target_x = args.target_x
    agent.target_y = args.target_y
    agent.decision_interval = args.decision_interval

    # Create LLM client
    llm = LLMClient(host=args.ollama_host, model=args.model)

    # Create MQTT client
    mqtt_client = HostileMQTTClient(
        hostile_id=args.hostile_id,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        site=args.site,
    )

    # Wire elimination callback
    def on_eliminated():
        agent.take_damage(999)
        print(f"[{args.hostile_id}] ELIMINATED!")

    def on_situation(data):
        agent.update_situation(data)

    mqtt_client.on_eliminated = on_eliminated
    mqtt_client.on_situation = on_situation

    # Shutdown handling
    running = True

    def shutdown(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start
    try:
        mqtt_client.start()
        mqtt_client.publish_status("active")
        print(f"[{args.hostile_id}] Hostile agent started at ({args.start_x}, {args.start_y})")
        print(f"[{args.hostile_id}] Target: ({args.target_x}, {args.target_y})")
        print(f"[{args.hostile_id}] LLM: {args.model} @ {args.ollama_host}")

        dt = 1.0 / args.tick_rate
        telemetry_counter = 0

        while running and agent.alive:
            agent.tick(dt)

            # LLM decision
            if agent.needs_decision() and agent.state.value not in ("spawning", "dead"):
                prompt = agent.build_decision_prompt()
                print(f"[{args.hostile_id}] Thinking...")
                response = llm.generate(prompt)
                action = agent.parse_llm_response(response)
                agent.apply_action(action)
                agent.reset_decision_timer()

                # Publish thought
                thought = f"[{action.upper()}] {response.strip().split(chr(10))[0][:100]}"
                agent.last_thought = thought
                mqtt_client.publish_thought(thought)
                print(f"[{args.hostile_id}] Decision: {action} -- {thought}")

            # Publish telemetry every 5 ticks (2Hz)
            telemetry_counter += 1
            if telemetry_counter >= 5:
                mqtt_client.publish_telemetry(agent.get_telemetry())
                telemetry_counter = 0

            time.sleep(dt)

        # Dead or stopped
        if not agent.alive:
            mqtt_client.publish_telemetry(agent.get_telemetry())
            mqtt_client.publish_status("eliminated")
            print(f"[{args.hostile_id}] Agent died. Final state: {agent.state.value}")
        else:
            print(f"[{args.hostile_id}] Shutting down.")

    finally:
        mqtt_client.stop()


if __name__ == "__main__":
    main()
