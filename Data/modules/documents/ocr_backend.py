"""Document AI / OCR backend — explicit probe, extract, readiness."""

from __future__ import annotations

import hashlib
import shutil
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from Data.modules.common.hashing import sha256_text


class ReadinessState(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    MISCONFIGURED = "MISCONFIGURED"


class OcrRetryClass(str, Enum):
    RETRYABLE = "RETRYABLE"
    TERMINAL = "TERMINAL"
    STRUCTURAL_UNAVAILABLE = "STRUCTURAL_UNAVAILABLE"
    USER_ACTION_REQUIRED = "USER_ACTION_REQUIRED"


@dataclass
class OcrReadiness:
    state: ReadinessState
    backend_name: str
    backend_version: str | None = None
    required_dependencies: list[str] = field(default_factory=list)
    detected_languages: list[str] = field(default_factory=list)
    last_probe_at: str | None = None
    failure_reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "backend_name": self.backend_name,
            "backend_version": self.backend_version,
            "required_dependencies": list(self.required_dependencies),
            "detected_languages": list(self.detected_languages),
            "last_probe_at": self.last_probe_at,
            "failure_reason": self.failure_reason,
            "details": dict(self.details),
        }


@dataclass
class OcrPageResult:
    page_number: int
    text: str
    confidence: float | None = None
    source: str = "ocr"


@dataclass
class OcrExtractResult:
    ok: bool
    text: str
    pages: list[OcrPageResult]
    backend_name: str
    backend_version: str | None
    languages: list[str]
    page_count: int
    ocr_page_count: int
    input_hash: str
    output_text_hash: str
    confidence_mean: float | None
    warnings: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    retry_class: OcrRetryClass | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "extracted_chars": len(self.text or ""),
            "pages": [
                {
                    "page_number": p.page_number,
                    "chars": len(p.text or ""),
                    "confidence": p.confidence,
                    "source": p.source,
                }
                for p in self.pages
            ],
            "backend_name": self.backend_name,
            "backend_version": self.backend_version,
            "languages": list(self.languages),
            "page_count": self.page_count,
            "ocr_page_count": self.ocr_page_count,
            "input_hash": self.input_hash,
            "output_text_hash": self.output_text_hash,
            "confidence_mean": self.confidence_mean,
            "warnings": list(self.warnings),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "retry_class": self.retry_class.value if self.retry_class else None,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class DocumentAIBackend(Protocol):
    def name(self) -> str: ...

    def version(self) -> str | None: ...

    def probe(self) -> OcrReadiness: ...

    def capabilities(self) -> dict[str, Any]: ...

    def health(self) -> OcrReadiness: ...

    def extract(
        self,
        path: Path,
        *,
        mime_type: str | None = None,
        languages: list[str] | None = None,
        native_pages: list[dict[str, Any]] | None = None,
    ) -> OcrExtractResult: ...


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 256)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


class TesseractDocumentBackend:
    """Tesseract OCR via pytesseract + Pillow; PDF pages rasterized with PyMuPDF when needed."""

    def __init__(self, *, lang: str = "eng") -> None:
        self._lang = lang
        self._last_readiness: OcrReadiness | None = None

    def name(self) -> str:
        return "tesseract"

    def version(self) -> str | None:
        ready = self.probe()
        return ready.backend_version

    def probe(self) -> OcrReadiness:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        deps = ["tesseract-ocr", "pytesseract", "Pillow"]
        binary = shutil.which("tesseract")
        if not binary:
            self._last_readiness = OcrReadiness(
                state=ReadinessState.UNAVAILABLE,
                backend_name=self.name(),
                required_dependencies=deps,
                last_probe_at=now,
                failure_reason="tesseract binary not on PATH",
            )
            return self._last_readiness
        try:
            import pytesseract  # noqa: WPS433
            from PIL import Image  # noqa: WPS433

            _ = Image
            ver = str(pytesseract.get_tesseract_version())
            langs_raw = pytesseract.get_languages(config="")
            langs = [str(x) for x in langs_raw if x]
            state = ReadinessState.AVAILABLE
            if self._lang not in langs and langs:
                state = ReadinessState.DEGRADED
            self._last_readiness = OcrReadiness(
                state=state,
                backend_name=self.name(),
                backend_version=ver,
                required_dependencies=deps,
                detected_languages=langs,
                last_probe_at=now,
                failure_reason=None if state == ReadinessState.AVAILABLE else f"lang {self._lang} not in tessdata",
                details={"binary": binary},
            )
            return self._last_readiness
        except Exception as exc:  # noqa: BLE001
            self._last_readiness = OcrReadiness(
                state=ReadinessState.MISCONFIGURED,
                backend_name=self.name(),
                required_dependencies=deps + ["pymupdf"],
                last_probe_at=now,
                failure_reason=str(exc)[:400],
            )
            return self._last_readiness

    def capabilities(self) -> dict[str, Any]:
        ready = self.probe()
        return {
            "backend": self.name(),
            "readiness": ready.public_dict(),
            "formats": {
                "png": True,
                "jpeg": True,
                "jpg": True,
                "tif": True,
                "tiff": True,
                "webp": True,
                "gif": True,
                "pdf_ocr": ready.state == ReadinessState.AVAILABLE,
            },
        }

    def health(self) -> OcrReadiness:
        return self.probe()

    def extract(
        self,
        path: Path,
        *,
        mime_type: str | None = None,
        languages: list[str] | None = None,
        native_pages: list[dict[str, Any]] | None = None,
    ) -> OcrExtractResult:
        started = _utc_now()
        ready = self.probe()
        input_hash = _file_hash(path)
        lang = "+".join(languages) if languages else self._lang
        if ready.state in {ReadinessState.UNAVAILABLE, ReadinessState.MISCONFIGURED}:
            return OcrExtractResult(
                ok=False,
                text="",
                pages=[],
                backend_name=self.name(),
                backend_version=ready.backend_version,
                languages=[lang],
                page_count=0,
                ocr_page_count=0,
                input_hash=input_hash,
                output_text_hash=sha256_text(""),
                confidence_mean=None,
                error_code="OCR_UNAVAILABLE",
                error_message=ready.failure_reason or "OCR backend unavailable",
                retry_class=OcrRetryClass.STRUCTURAL_UNAVAILABLE,
                started_at=started,
                finished_at=_utc_now(),
            )

        suffix = path.suffix.lower()
        mt = (mime_type or "").lower()
        is_pdf = suffix == ".pdf" or "pdf" in mt
        is_image = suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".gif"} or mt.startswith(
            "image/"
        )

        if not is_pdf and not is_image:
            return OcrExtractResult(
                ok=False,
                text="",
                pages=[],
                backend_name=self.name(),
                backend_version=ready.backend_version,
                languages=[lang],
                page_count=0,
                ocr_page_count=0,
                input_hash=input_hash,
                output_text_hash=sha256_text(""),
                confidence_mean=None,
                error_code="UNSUPPORTED_FORMAT",
                error_message=f"OCR unsupported for {suffix or mt}",
                retry_class=OcrRetryClass.TERMINAL,
                started_at=started,
                finished_at=_utc_now(),
            )

        try:
            import pytesseract  # noqa: WPS433
            from PIL import Image  # noqa: WPS433

            pages: list[OcrPageResult] = []
            warnings: list[str] = []
            native = list(native_pages or [])
            native_by_num = {int(p.get("page_number") or i + 1): str(p.get("text") or "") for i, p in enumerate(native)}

            def _ocr_image(img: Image.Image, page_number: int) -> None:
                text = pytesseract.image_to_string(img, lang=lang) or ""
                conf = None
                try:
                    data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
                    confs = [float(c) for c in data.get("conf", []) if str(c).lstrip("-").isdigit() and float(c) >= 0]
                    if confs:
                        conf = sum(confs) / len(confs) / 100.0
                except Exception:  # noqa: BLE001
                    pass
                pages.append(OcrPageResult(page_number=page_number, text=text.strip(), confidence=conf, source="ocr"))

            if is_image:
                with Image.open(path) as img:
                    _ocr_image(img.convert("RGB"), 1)
            else:
                try:
                    import fitz  # noqa: WPS433 — PyMuPDF

                    doc = fitz.open(str(path))
                    page_count = doc.page_count
                    for idx in range(page_count):
                        page_no = idx + 1
                        native_text = (native_by_num.get(page_no) or "").strip()
                        if native_text:
                            pages.append(
                                OcrPageResult(
                                    page_number=page_no,
                                    text=native_text,
                                    confidence=None,
                                    source="native",
                                )
                            )
                            continue
                        page = doc.load_page(idx)
                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                        _ocr_image(img, page_no)
                    doc.close()
                except Exception as exc:  # noqa: BLE001
                    return OcrExtractResult(
                        ok=False,
                        text="",
                        pages=[],
                        backend_name=self.name(),
                        backend_version=ready.backend_version,
                        languages=[lang],
                        page_count=0,
                        ocr_page_count=0,
                        input_hash=input_hash,
                        output_text_hash=sha256_text(""),
                        confidence_mean=None,
                        error_code="OCR_FAILED",
                        error_message=f"PDF rasterize/OCR failed: {exc}"[:400],
                        retry_class=OcrRetryClass.TERMINAL,
                        started_at=started,
                        finished_at=_utc_now(),
                    )

            # Deterministic page order merge
            pages.sort(key=lambda p: p.page_number)
            combined_parts: list[str] = []
            confs: list[float] = []
            ocr_count = 0
            for p in pages:
                if p.text:
                    combined_parts.append(f"--- page {p.page_number} ({p.source}) ---\n{p.text}")
                if p.source == "ocr":
                    ocr_count += 1
                if p.confidence is not None:
                    confs.append(p.confidence)
            combined = "\n\n".join(combined_parts).strip()
            if not combined:
                return OcrExtractResult(
                    ok=False,
                    text="",
                    pages=pages,
                    backend_name=self.name(),
                    backend_version=ready.backend_version,
                    languages=[lang],
                    page_count=len(pages),
                    ocr_page_count=ocr_count,
                    input_hash=input_hash,
                    output_text_hash=sha256_text(""),
                    confidence_mean=None,
                    error_code="OCR_FAILED",
                    error_message="OCR produced no text",
                    retry_class=OcrRetryClass.TERMINAL,
                    warnings=warnings,
                    started_at=started,
                    finished_at=_utc_now(),
                )
            mean_conf = sum(confs) / len(confs) if confs else None
            return OcrExtractResult(
                ok=True,
                text=combined,
                pages=pages,
                backend_name=self.name(),
                backend_version=ready.backend_version,
                languages=[lang],
                page_count=len(pages),
                ocr_page_count=ocr_count,
                input_hash=input_hash,
                output_text_hash=sha256_text(combined),
                confidence_mean=mean_conf,
                warnings=warnings,
                started_at=started,
                finished_at=_utc_now(),
            )
        except Exception as exc:  # noqa: BLE001
            return OcrExtractResult(
                ok=False,
                text="",
                pages=[],
                backend_name=self.name(),
                backend_version=ready.backend_version,
                languages=[lang],
                page_count=0,
                ocr_page_count=0,
                input_hash=input_hash,
                output_text_hash=sha256_text(""),
                confidence_mean=None,
                error_code="OCR_FAILED",
                error_message=str(exc)[:400],
                retry_class=OcrRetryClass.RETRYABLE,
                started_at=started,
                finished_at=_utc_now(),
            )


_BACKEND: DocumentAIBackend | None = None


def get_document_ai_backend(*, force_refresh: bool = False) -> DocumentAIBackend:
    global _BACKEND
    if _BACKEND is None or force_refresh:
        import os

        lang = (os.environ.get("LEVIATHAN_OCR_LANG") or "eng").strip() or "eng"
        _BACKEND = TesseractDocumentBackend(lang=lang)
    return _BACKEND


def probe_document_ai_readiness() -> OcrReadiness:
    return get_document_ai_backend().probe()
