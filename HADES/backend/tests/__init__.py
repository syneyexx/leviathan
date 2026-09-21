"""Backend unittest package marker.

``unittest discover -s tests`` imports modules as top-level ``test_*.py``, so this
file is not always loaded. ``verify_hades.py`` imports ``win_temp_patch`` before
discovery; keep a matching install here for ``python -m unittest tests...`` runs.
"""

from __future__ import annotations

try:
    from .win_temp_patch import install as _install_win_temp

    _install_win_temp()
except Exception:
    try:
        from win_temp_patch import install as _install_win_temp

        _install_win_temp()
    except Exception:
        pass
