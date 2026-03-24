# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Re-export from tritium-lib. SC shim for backward compatibility."""
from tritium_lib.inference.model_router import *  # noqa: F401,F403
from tritium_lib.inference.model_router import (  # noqa: F401 — explicit re-exports
    TaskType,
    ModelProfile,
    AllHostsFailedError,
    ModelRouter,
)
