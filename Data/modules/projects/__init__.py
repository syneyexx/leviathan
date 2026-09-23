"""Projects / Workspaces — first-class product scope (Wave 11)."""

from .continuity import ContinuityPlane, SessionHandoff
from .plane import ProductUnificationPlane
from .store import ProjectBinding, ProjectRecord, ProjectStore, WorkspaceRecord

__all__ = [
    "ContinuityPlane",
    "ProductUnificationPlane",
    "ProjectBinding",
    "ProjectRecord",
    "ProjectStore",
    "SessionHandoff",
    "WorkspaceRecord",
]
