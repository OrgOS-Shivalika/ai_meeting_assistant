"""Phase 7H — agent tool registry + permission enforcement.

Two modules:

  registry.py    — `ToolDescriptor` catalog. Today's entries are
                   stubs that raise NotImplementedError. Future tool
                   handlers register here and become callable.
  permissions.py — `enforce_tool_permission(resolved_config, tool_id)`
                   raises `PermissionDeniedError` when the resolved
                   bundle's tool_permissions disallow the call.

This package is loaded eagerly so registered stubs are visible on
the dashboard's tool-permissions picker.
"""
from app.services.tools.registry import (
    ToolDescriptor, get_tool, list_tools, register_tool,
)
from app.services.tools.permissions import (
    PermissionDeniedError, enforce_tool_permission,
)

__all__ = [
    "ToolDescriptor",
    "get_tool",
    "list_tools",
    "register_tool",
    "PermissionDeniedError",
    "enforce_tool_permission",
]
