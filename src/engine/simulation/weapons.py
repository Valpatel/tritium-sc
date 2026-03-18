"""Re-export from tritium-lib for backwards compatibility."""
from tritium_lib.sim_engine.combat.weapons import *  # noqa: F401,F403
# Private names needed by tests
try:
    from tritium_lib.sim_engine.combat.weapons import _DEFAULT_WEAPONS  # noqa: F401
except ImportError:
    pass
