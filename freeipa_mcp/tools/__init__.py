# SPDX-License-Identifier: GPL-3.0-or-later
"""
FreeIPA MCP Tools.

Custom tool implementations are imported here to trigger registration.
"""

# Import vault to register custom executors
from . import vault  # noqa: F401
