from __future__ import annotations

from typing import Any

from Data.modules.execution.file_io_thresholds import load_file_io_thresholds
from Data.modules.file_io.errors import FileIoError
from Data.modules.file_io.ops import write_text_streaming


def run(
    path: str,
    content: str | None = None,
    *,
    create_parents: bool = True,
    content_path: str | None = None,
    content_artifact_id: str | None = None,
) -> dict[str, Any]:
    """Write UTF-8 text to a local file (atomic). Side effect: WRITE.

    Large payloads should arrive via ``content_path`` / artifact staging rather
    than multi-hundred-MB JSON ``content`` bodies.
    """
    thresholds = load_file_io_thresholds()
    if content_artifact_id and not content_path:
        raise ValueError(
            "content_artifact_id requires a resolved content_path "
            "(ArtifactStore staging) before dispatch"
        )
    if content is not None and content_path is None:
        size = len(str(content).encode("utf-8"))
        if size > thresholds.max_inline_write_bytes * 4:
            # Hard refuse absurd inline bodies even on workers — use staging.
            raise ValueError(
                f"Inline content exceeds safe body limit ({size} bytes); "
                "pass content_path / artifact staging instead"
            )
    try:
        return write_text_streaming(
            path,
            content,
            content_path=content_path,
            create_parents=create_parents,
        )
    except FileIoError as exc:
        raise ValueError(exc.message) from exc
