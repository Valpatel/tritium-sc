"""Amy — AI Commander for TRITIUM-SC.

Factory function auto-detects available hardware and creates Amy
with the appropriate sensor nodes.
"""

from __future__ import annotations

__version__ = "0.1.0"


def create_amy(settings=None, simulation_engine=None) -> "Commander":
    """Create and configure an Amy Commander instance.

    Auto-detects available hardware:
    - BCC950 PTZ camera → BCC950Node (camera + mic + speaker + PTZ)
    - Falls back to VirtualNode if no hardware found

    Args:
        settings: Pydantic settings object (from app.config) or None for defaults.
        simulation_engine: Optional SimulationEngine for virtual targets.

    Returns:
        A Commander instance ready to be started with .run()
    """
    from .commander import Commander
    from .nodes.virtual import VirtualNode

    # Read config from settings (or use defaults)
    deep_model = "llava:7b"
    chat_model = "gemma3:4b"
    whisper_model = "large-v3"
    tts_enabled = True
    wake_word = "amy"
    camera_device = None
    think_interval = 8.0
    ollama_host = "http://localhost:11434"

    if settings is not None:
        deep_model = getattr(settings, "amy_deep_model", deep_model)
        chat_model = getattr(settings, "amy_chat_model", chat_model)
        whisper_model = getattr(settings, "amy_whisper_model", whisper_model)
        tts_enabled = getattr(settings, "amy_tts_enabled", tts_enabled)
        wake_word = getattr(settings, "amy_wake_word", wake_word)
        camera_device = getattr(settings, "amy_camera_device", camera_device)
        think_interval = getattr(settings, "amy_think_interval", think_interval)
        ollama_host = getattr(settings, "ollama_host", ollama_host)

    # Set Ollama host for all Amy vision/LLM calls
    from .vision import set_ollama_host
    set_ollama_host(ollama_host)

    # Auto-detect hardware
    nodes = {}

    # Try BCC950
    try:
        from .nodes.bcc950 import BCC950Node
        node = BCC950Node(device=camera_device)
        # Don't start yet — just check if bcc950 package is importable
        # and the constructor doesn't fail
        nodes["bcc950"] = node
        print("  [Amy] BCC950 node registered (will init on boot)")
    except Exception as e:
        print(f"  [Amy] BCC950 not available: {e}")

    # Fallback to virtual if no hardware
    if not nodes:
        nodes["virtual"] = VirtualNode()
        print("  [Amy] No hardware detected — using virtual node")

    commander = Commander(
        nodes=nodes,
        deep_model=deep_model,
        chat_model=chat_model,
        whisper_model=whisper_model,
        use_tts=tts_enabled,
        wake_word=wake_word,
        think_interval=think_interval,
        simulation_engine=simulation_engine,
    )

    # Set initial tactical mode from config
    initial_mode = getattr(settings, "simulation_mode", "sim") if settings else "sim"
    if initial_mode in ("sim", "live"):
        commander._mode = initial_mode

    return commander
