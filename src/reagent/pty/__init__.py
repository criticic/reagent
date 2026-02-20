"""PTY process management — managed pseudo-terminal sessions.

All interactive RE tools (debuggers, shells) run in managed PTY sessions
with process group isolation, output buffering, ANSI stripping, and
automatic cleanup.
"""

from reagent.pty.session import PTYSession, PTYStatus
from reagent.pty.manager import PTYManager
from reagent.pty.buffer import RollingBuffer

__all__ = [
    "PTYSession",
    "PTYStatus",
    "PTYManager",
    "RollingBuffer",
]
