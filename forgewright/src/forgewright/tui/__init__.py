"""Terminal UI for forgewright (Textual).

Connects to the same FastAPI ``/api/sessions`` surface as the web chat.
Requires the ``[tui]`` extra (``textual``).
"""

from forgewright.tui.app import ForgewrightTuiApp

__all__ = ["ForgewrightTuiApp"]
