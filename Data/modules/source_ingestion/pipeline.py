"""Source ingestion pipeline — detect, expand, parse, Brain-sync with checkpoints."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable

from Data.modules.common.atomic import atomic_write_text, ensure_dir
from Data.modules.common.hashing import sha256_text
from Data.modules.common.secrets import redact_secrets
from Data.modules.research.store import ResearchStore, utc_now
from Data.modules.research.types import (
    BrainStatus,
    ParseStatus,
    ResearchSource,
    SourceType,
)

from .archives.security import project_signals
from .archives.tar_safe import decompress_gzip_single, extract_tar_member, inspect_tar
from .archives.zip_safe import (
    extract_member_to_staging,
    inspect_zip,
    member_to_manifest,
    open_zip,
    read_member_sample,
)
from .detection import detect_source_type
from .handlers import get_default_registry
from .secrets_policy import sample_file_prefix, should_quarantine
from .settings import SourceIngestionSettings
from .skip_policy import should_skip_path
from .store import IngestionStore
from .types import (
    ArchiveManifest,
    IngestionError,
    IngestionPhase,
    IngestionProgress,
    ManifestMember,
    MemberOutcome,
    NormalizedArtifact,
    PARSER_VERSION,
    SourceKind,
)


EmitFn = Callable[[str, str, dict[str, Any]], None]


class SourceIngestionPipeline:
    """Process a stored source (file or archive) outside the upload request path."""

    def __init__(
        self,
        *,
        research_store: ResearchStore,
        ingestion_store: IngestionStore,
        settings: SourceIngestionSettings,
        knowledge: Any | None = None,
        snapshots_root: Path,
        staging_root: Path,
        dataset_service: Any | None = None,
        emit: EmitFn | None = None,
    ) -> None:
        self.research = research_store
        self.ingestion = ingestion_store
        self.settings = settings
        self.knowledge = knowledge
        self.snapshots_root = ensure_dir(Path(snapshots_root))
        self.staging_root = ensure_dir(Path(staging_root))
        self.dataset_service = dataset_service
        self.emit = emit
        self.registry = get_default_registry()

    def _event(self, name: str, message: str, payload: dict[str, Any]) -> None:
        if self.emit is not None:
            try:
                self.emit(name, message, payload)
            except Exception:  # noqa: BLE001
                pass

    def process_source(self, source_id: str, *, nested_depth: int = 0) -> IngestionProgress:
        source = self.research.get_source(source_id)
        if source is None:
            raise IngestionError("SOURCE_NOT_FOUND", f"Unknown source: {source_id}", http_status=404)

        raw_path = Path(str((source.provenance or {}).get("raw_path") or ""))
        if not raw_path.exists():
            raise IngestionError(
                "SOURCE_RAW_MISSING",
                "Raw upload file missing",
                http_status=404,
                details={"source_id": source_id},
            )

        sample = sample_file_prefix(raw_path)
        detection = detect_source_type(
            filename=source.title or raw_path.name,
            sample=sample,
            content_type_hint=source.mime_type,
            allow_unknown_text=self.settings.allow_unknown_text,
        )

        self.ingestion.upsert_container(
            container_source_id=source_id,
            project_id=source.project_id,
            filename=source.title,
            archive_type=detection.handler_hint if detection.is_archive else None,
            phase=IngestionPhase.INSPECTING,
            compressed_bytes=int((source.provenance or {}).get("size_bytes") or raw_path.stat().st_size),
        )

        if detection.is_archive:
            return self._process_archive(source, raw_path, detection, nested_depth=nested_depth)
        return self._process_single(source, raw_path, detection)

    def _process_single(
        self,
        source: ResearchSource,
        raw_path: Path,
        detection: Any,
    ) -> IngestionProgress:
        if self.ingestion.is_cancel_requested(source.source_id):
            return self._finalize_phase(source.source_id, IngestionPhase.CANCELLED)

        # Empty file
        if raw_path.stat().st_size == 0:
            updated = self._save_source_state(
                source,
                parse_status=ParseStatus.OK,
                brain_status=BrainStatus.SKIPPED,
                parser="empty",
                text="",
                detection=detection,
                extra_meta={"empty": True},
            )
            self.ingestion.upsert_container(
                container_source_id=source.source_id,
                project_id=source.project_id,
                phase=IngestionPhase.COMPLETED,
            )
            return self.get_progress(source.source_id)

        # Secrets
        sample = sample_file_prefix(raw_path)
        quarantine, reason = should_quarantine(
            relative_path=source.title or raw_path.name,
            sample=sample,
            policy=self.settings.secret_policy,
        )
        if quarantine:
            self._save_source_state(
                source,
                parse_status=ParseStatus.SKIPPED,
                brain_status=BrainStatus.SKIPPED,
                parser="secrets_policy",
                text="",
                detection=detection,
                extra_meta={"quarantine_reason": reason},
                brain_error=reason,
            )
            self.ingestion.upsert_container(
                container_source_id=source.source_id,
                project_id=source.project_id,
                phase=IngestionPhase.QUARANTINED,
            )
            self._event("security_skip", reason or "quarantined", {"source_id": source.source_id})
            return self.get_progress(source.source_id)

        handler = self.registry.resolve(detection, filename=source.title or raw_path.name)
        if handler is None:
            self._save_source_state(
                source,
                parse_status=ParseStatus.SKIPPED,
                brain_status=BrainStatus.SKIPPED,
                parser="unsupported",
                text="",
                detection=detection,
                extra_meta={"skip_reason": "unsupported"},
            )
            self.ingestion.upsert_container(
                container_source_id=source.source_id,
                project_id=source.project_id,
                phase=IngestionPhase.COMPLETED,
            )
            return self.get_progress(source.source_id)

        self.ingestion.upsert_container(
            container_source_id=source.source_id,
            project_id=source.project_id,
            phase=IngestionPhase.PARSING,
        )
        artifact = handler.ingest(
            raw_path,
            detection=detection,
            relative_path=source.title or raw_path.name,
            settings=self.settings,
        )
        return self._finalize_artifact(source, artifact, detection, is_child=False)

    def _finalize_artifact(
        self,
        source: ResearchSource,
        artifact: NormalizedArtifact,
        detection: Any,
        *,
        is_child: bool,
        archive_filename: str | None = None,
        parent_source_id: str | None = None,
        container_source_id: str | None = None,
    ) -> IngestionProgress:
        if artifact.outcome == MemberOutcome.ROUTED and artifact.route_target == "dataset":
            self._route_dataset(source, artifact)
            self._save_source_state(
                source,
                parse_status=ParseStatus.SKIPPED,
                brain_status=BrainStatus.NOT_APPLICABLE,
                parser=artifact.parser,
                text="",
                detection=detection,
                artifact=artifact,
                archive_filename=archive_filename,
                parent_source_id=parent_source_id,
                container_source_id=container_source_id,
            )
            if not is_child:
                self.ingestion.upsert_container(
                    container_source_id=source.source_id,
                    project_id=source.project_id,
                    phase=IngestionPhase.COMPLETED,
                )
            return self.get_progress(container_source_id or source.source_id)

        if artifact.outcome in {MemberOutcome.SKIPPED, MemberOutcome.QUARANTINED, MemberOutcome.FAILED}:
            status = (
                ParseStatus.FAILED
                if artifact.outcome == MemberOutcome.FAILED
                else ParseStatus.SKIPPED
            )
            self._save_source_state(
                source,
                parse_status=status,
                brain_status=BrainStatus.SKIPPED,
                parser=artifact.parser,
                text="",
                detection=detection,
                artifact=artifact,
                archive_filename=archive_filename,
                parent_source_id=parent_source_id,
                container_source_id=container_source_id,
                brain_error=artifact.skip_reason or artifact.error_code,
            )
            if not is_child:
                phase = (
                    IngestionPhase.FAILED
                    if artifact.outcome == MemberOutcome.FAILED
                    else IngestionPhase.COMPLETED
                )
                if artifact.outcome == MemberOutcome.QUARANTINED:
                    phase = IngestionPhase.QUARANTINED
                self.ingestion.upsert_container(
                    container_source_id=source.source_id,
                    project_id=source.project_id,
                    phase=phase,
                )
            return self.get_progress(container_source_id or source.source_id)

        text = artifact.content.read_text()
        # Never silently truncate canonical content.
        snap = self._write_snapshot(source.project_id, source.source_id, text)
        updated = self._save_source_state(
            source,
            parse_status=ParseStatus.OK,
            brain_status=BrainStatus.PENDING,
            parser=artifact.parser,
            text=text,
            detection=detection,
            artifact=artifact,
            snapshot_path=str(snap),
            archive_filename=archive_filename,
            parent_source_id=parent_source_id,
            container_source_id=container_source_id,
        )
        synced = self._brain_sync(updated, text, artifact=artifact)
        if not is_child:
            phase = IngestionPhase.COMPLETED if synced.brain_status == BrainStatus.SYNCED else IngestionPhase.PARTIAL
            if synced.brain_status == BrainStatus.FAILED:
                phase = IngestionPhase.PARTIAL
            self.ingestion.upsert_container(
                container_source_id=source.source_id,
                project_id=source.project_id,
                phase=phase,
            )
        return self.get_progress(container_source_id or source.source_id)

    def _process_archive(
        self,
        source: ResearchSource,
        raw_path: Path,
        detection: Any,
        *,
        nested_depth: int,
    ) -> IngestionProgress:
        if nested_depth > self.settings.max_nested_archive_depth:
            self._save_source_state(
                source,
                parse_status=ParseStatus.SKIPPED,
                brain_status=BrainStatus.SKIPPED,
                parser="archive",
                text="",
                detection=detection,
                extra_meta={"skip_reason": "nested_depth_exceeded", "nested_depth": nested_depth},
            )
            self.ingestion.upsert_container(
                container_source_id=source.source_id,
                project_id=source.project_id,
                phase=IngestionPhase.SKIPPED,
                error="nested_depth_exceeded",
            )
            return self.get_progress(source.source_id)

        archive_type = detection.handler_hint or detection.extension.lstrip(".")
        self.ingestion.upsert_container(
            container_source_id=source.source_id,
            project_id=source.project_id,
            filename=source.title,
            archive_type=archive_type,
            phase=IngestionPhase.EXPANDING,
            compressed_bytes=raw_path.stat().st_size,
        )
        self._event("archive_inspection_started", source.title or "", {"source_id": source.source_id})

        staging = ensure_dir(self.staging_root / source.project_id / source.source_id)

        try:
            if archive_type in {"zip", "zip_or_office"} or detection.extension == ".zip":
                return self._process_zip(source, raw_path, detection, staging, nested_depth=nested_depth)
            if archive_type in {"tar", "gzip"} or detection.extension in {
                ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz",
            }:
                if detection.extension == ".gz" and archive_type == "gzip":
                    return self._process_gzip_single(source, raw_path, detection, staging, nested_depth=nested_depth)
                return self._process_tar(source, raw_path, detection, staging, nested_depth=nested_depth)
            if detection.extension == ".gz":
                return self._process_gzip_single(source, raw_path, detection, staging, nested_depth=nested_depth)
            if detection.extension in {".7z", ".rar"}:
                reason = "unsupported_archive_format"
                self._save_source_state(
                    source,
                    parse_status=ParseStatus.FAILED,
                    brain_status=BrainStatus.SKIPPED,
                    parser="archive",
                    text="",
                    detection=detection,
                    extra_meta={"skip_reason": reason, "format": detection.extension},
                )
                self.ingestion.upsert_container(
                    container_source_id=source.source_id,
                    project_id=source.project_id,
                    phase=IngestionPhase.FAILED,
                    error=reason,
                )
                return self.get_progress(source.source_id)
            raise IngestionError(
                "UNSUPPORTED_ARCHIVE",
                f"Unsupported archive type: {archive_type}",
                http_status=422,
            )
        except IngestionError as exc:
            self.ingestion.upsert_container(
                container_source_id=source.source_id,
                project_id=source.project_id,
                phase=IngestionPhase.FAILED,
                error=redact_secrets(exc.message),
            )
            self._save_source_state(
                source,
                parse_status=ParseStatus.FAILED,
                brain_status=BrainStatus.SKIPPED,
                parser="archive",
                text="",
                detection=detection,
                extra_meta={"error_code": exc.code, "error": redact_secrets(exc.message)},
                brain_error=redact_secrets(exc.message),
            )
            self._event("ingestion_failed", exc.message, {"source_id": source.source_id, "code": exc.code})
            return self.get_progress(source.source_id)

    def _process_zip(
        self,
        source: ResearchSource,
        raw_path: Path,
        detection: Any,
        staging: Path,
        *,
        nested_depth: int,
    ) -> IngestionProgress:
        # Resume: if members already exist, skip re-inspection
        existing_counts = self.ingestion.count_members(source.source_id)
        if int(existing_counts.get("total") or 0) == 0:
            zip_members, meta = inspect_zip(
                raw_path,
                container_source_id=source.source_id,
                settings=self.settings,
            )
            rels = [m.relative_path for m in zip_members if not m.is_dir]
            signals = project_signals(rels)
            self.ingestion.upsert_container(
                container_source_id=source.source_id,
                project_id=source.project_id,
                archive_type="zip",
                phase=IngestionPhase.CLASSIFYING,
                compressed_bytes=int(meta.get("compressed_bytes") or 0),
                uncompressed_bytes=int(meta.get("declared_uncompressed_bytes") or 0),
                manifest_meta={**meta, **signals},
            )
            for zm in zip_members:
                mm = member_to_manifest(
                    zm,
                    container_source_id=source.source_id,
                    member_id=str(uuid.uuid4()),
                )
                self.ingestion.upsert_member(mm)
            self._event(
                "archive_manifest_completed",
                f"{len(rels)} members",
                {"source_id": source.source_id, "files": len(rels)},
            )
            # Mark parent as container
            self._mark_container_source(source, detection, meta={**meta, **signals})

        return self._process_pending_zip_members(
            source, raw_path, staging, nested_depth=nested_depth
        )

    def _process_pending_zip_members(
        self,
        source: ResearchSource,
        raw_path: Path,
        staging: Path,
        *,
        nested_depth: int,
    ) -> IngestionProgress:
        self.ingestion.upsert_container(
            container_source_id=source.source_id,
            project_id=source.project_id,
            phase=IngestionPhase.PARSING,
        )
        processed = 0
        with open_zip(raw_path) as zf:
            while True:
                if self.ingestion.is_cancel_requested(source.source_id):
                    self.ingestion.upsert_container(
                        container_source_id=source.source_id,
                        project_id=source.project_id,
                        phase=IngestionPhase.CANCELLED,
                    )
                    return self.get_progress(source.source_id)

                batch = self.ingestion.list_pending_members(source.source_id, limit=50)
                if not batch:
                    break
                info_by_name = {i.filename.replace("\\", "/"): i for i in zf.infolist()}
                # Also index by normalized path
                from .archives.security import normalize_member_path
                from Data.modules.common.paths import PathEscapeError

                norm_map = {}
                for info in zf.infolist():
                    try:
                        norm_map[normalize_member_path(info.filename)] = info
                    except PathEscapeError:
                        continue

                for member in batch:
                    self._process_one_zip_member(
                        source,
                        zf,
                        member,
                        norm_map.get(member.relative_path),
                        staging,
                        nested_depth=nested_depth,
                    )
                    processed += 1
                    if processed % 25 == 0:
                        prog = self.get_progress(source.source_id)
                        self._event(
                            "ingestion_progress",
                            f"{prog.files_ingested}/{prog.files_discovered}",
                            prog.public_dict(),
                        )

        return self._finalize_container(source.source_id)

    def _process_one_zip_member(
        self,
        source: ResearchSource,
        zf: Any,
        member: ManifestMember,
        info: Any | None,
        staging: Path,
        *,
        nested_depth: int,
    ) -> None:
        if member.is_directory:
            member.outcome = MemberOutcome.SKIPPED
            member.skip_reason = "directory"
            self.ingestion.upsert_member(member)
            return
        if member.is_symlink:
            member.outcome = MemberOutcome.SKIPPED
            member.skip_reason = "symlink"
            self.ingestion.upsert_member(member)
            return
        if member.is_encrypted or (info is not None and bool(info.flag_bits & 0x1)):
            member.outcome = MemberOutcome.QUARANTINED
            member.skip_reason = "encrypted"
            member.parse_status = "skipped"
            self.ingestion.upsert_member(member)
            return
        if info is None:
            member.outcome = MemberOutcome.FAILED
            member.error_code = "MEMBER_MISSING"
            member.skip_reason = "member_not_found_in_archive"
            member.parse_status = "failed"
            self.ingestion.upsert_member(member)
            return

        skip, skip_reason = should_skip_path(
            member.relative_path,
            enabled=self.settings.code_repo_ignore_defaults,
        )
        if skip:
            member.outcome = MemberOutcome.SKIPPED
            member.skip_reason = skip_reason
            member.parse_status = "skipped"
            self.ingestion.upsert_member(member)
            return

        try:
            sample = read_member_sample(zf, info)
        except Exception:  # noqa: BLE001
            sample = b""

        quarantine, q_reason = should_quarantine(
            relative_path=member.relative_path,
            sample=sample,
            policy=self.settings.secret_policy,
        )
        if quarantine:
            member.outcome = MemberOutcome.QUARANTINED
            member.skip_reason = q_reason
            member.parse_status = "skipped"
            member.brain_status = "skipped"
            self.ingestion.upsert_member(member)
            self._event("security_skip", q_reason or "quarantined", {
                "source_id": source.source_id,
                "relative_path": member.relative_path,
            })
            return

        detection = detect_source_type(
            filename=member.relative_path,
            sample=sample,
            allow_unknown_text=self.settings.allow_unknown_text,
        )
        member.detection = detection.public_dict()
        member.detected_kind = detection.kind.value
        member.mime_type = detection.mime_type

        # Nested archive depth
        if detection.is_archive:
            if nested_depth + 1 > self.settings.max_nested_archive_depth:
                member.outcome = MemberOutcome.SKIPPED
                member.skip_reason = "nested_depth_exceeded"
                member.parse_status = "skipped"
                self.ingestion.upsert_member(member)
                return

        try:
            dest, content_hash, size = extract_member_to_staging(
                zf,
                info,
                relative_path=member.relative_path,
                staging_root=staging,
                settings=self.settings,
            )
        except IngestionError as exc:
            member.outcome = MemberOutcome.FAILED
            member.error_code = exc.code
            member.skip_reason = redact_secrets(exc.message)
            member.parse_status = "failed"
            self.ingestion.upsert_member(member)
            return

        member.content_hash = content_hash
        member.size_bytes = size

        # Nested archive: materialize and recurse (do not treat as unsupported binary).
        if detection.is_archive:
            child = self._ensure_child_source(
                parent=source,
                member=member,
                detection=detection,
                raw_path=dest,
            )
            self._mark_container_source(child, detection, meta={"nested": True, "parent": source.source_id})
            try:
                nested_progress = self.process_source(child.source_id, nested_depth=nested_depth + 1)
                member.outcome = MemberOutcome.SUCCESS
                member.parse_status = "ok"
                member.brain_status = "not_applicable"
                member.child_source_id = child.source_id
                member.parser = "archive"
                member.metadata = {
                    **member.metadata,
                    "nested_status": nested_progress.status.value,
                    "nested_ingested": nested_progress.files_ingested,
                }
            except Exception as exc:  # noqa: BLE001
                member.outcome = MemberOutcome.FAILED
                member.error_code = "NESTED_ARCHIVE_FAILED"
                member.skip_reason = redact_secrets(str(exc))[:200]
                member.parse_status = "failed"
                member.child_source_id = child.source_id
            self.ingestion.upsert_member(member)
            return

        # Duplicate content within archive: still register path provenance
        child = self._ensure_child_source(
            parent=source,
            member=member,
            detection=detection,
            raw_path=dest,
        )

        handler = self.registry.resolve(detection, filename=member.relative_path)
        if handler is None:
            member.outcome = MemberOutcome.SKIPPED
            member.skip_reason = "unsupported"
            member.parse_status = "skipped"
            member.child_source_id = child.source_id
            self.ingestion.upsert_member(member)
            return

        artifact = handler.ingest(
            dest,
            detection=detection,
            relative_path=member.relative_path,
            settings=self.settings,
            staging_root=staging,
        )
        member.parser = artifact.parser

        if artifact.outcome == MemberOutcome.ROUTED:
            self._route_dataset(child, artifact)
            member.outcome = MemberOutcome.ROUTED
            member.skip_reason = artifact.skip_reason
            member.parse_status = "skipped"
            member.brain_status = "not_applicable"
            member.child_source_id = child.source_id
            self.ingestion.upsert_member(member)
            self._save_source_state(
                child,
                parse_status=ParseStatus.SKIPPED,
                brain_status=BrainStatus.NOT_APPLICABLE,
                parser=artifact.parser,
                text="",
                detection=detection,
                artifact=artifact,
                archive_filename=source.title,
                parent_source_id=source.source_id,
                container_source_id=source.source_id,
            )
            return

        if artifact.outcome != MemberOutcome.SUCCESS:
            member.outcome = artifact.outcome
            member.skip_reason = artifact.skip_reason
            member.error_code = artifact.error_code
            member.parse_status = "failed" if artifact.outcome == MemberOutcome.FAILED else "skipped"
            member.brain_status = "skipped"
            member.child_source_id = child.source_id
            self.ingestion.upsert_member(member)
            self._save_source_state(
                child,
                parse_status=ParseStatus.FAILED if artifact.outcome == MemberOutcome.FAILED else ParseStatus.SKIPPED,
                brain_status=BrainStatus.SKIPPED,
                parser=artifact.parser,
                text="",
                detection=detection,
                artifact=artifact,
                archive_filename=source.title,
                parent_source_id=source.source_id,
                container_source_id=source.source_id,
            )
            return

        text = artifact.content.read_text()
        # Dedupe Brain by content hash; child source still unique by path
        snap = self._write_snapshot(source.project_id, child.source_id, text)
        updated = self._save_source_state(
            child,
            parse_status=ParseStatus.OK,
            brain_status=BrainStatus.PENDING,
            parser=artifact.parser,
            text=text,
            detection=detection,
            artifact=artifact,
            snapshot_path=str(snap),
            archive_filename=source.title,
            parent_source_id=source.source_id,
            container_source_id=source.source_id,
            content_hash_override=artifact.content_hash,
        )
        # Duplicate detection: same content_hash already brain-synced elsewhere
        synced = self._brain_sync(updated, text, artifact=artifact)
        member.outcome = MemberOutcome.SUCCESS
        member.parse_status = "ok"
        member.brain_status = synced.brain_status.value
        member.brain_document_id = synced.brain_document_id
        member.child_source_id = synced.source_id
        member.content_hash = artifact.content_hash
        self.ingestion.upsert_member(member)
    def _process_tar(
        self,
        source: ResearchSource,
        raw_path: Path,
        detection: Any,
        staging: Path,
        *,
        nested_depth: int,
    ) -> IngestionProgress:
        existing = self.ingestion.count_members(source.source_id)
        if int(existing.get("total") or 0) == 0:
            tar_members, meta = inspect_tar(raw_path, settings=self.settings)
            rels = [m["relative_path"] for m in tar_members if not m["is_dir"]]
            signals = project_signals(rels)
            self.ingestion.upsert_container(
                container_source_id=source.source_id,
                project_id=source.project_id,
                archive_type="tar",
                phase=IngestionPhase.CLASSIFYING,
                compressed_bytes=int(meta.get("compressed_bytes") or 0),
                uncompressed_bytes=int(meta.get("declared_uncompressed_bytes") or 0),
                manifest_meta={**meta, **signals},
            )
            for tm in tar_members:
                mm = ManifestMember(
                    member_id=str(uuid.uuid4()),
                    container_source_id=source.source_id,
                    relative_path=tm["relative_path"],
                    original_filename=Path(tm["relative_path"]).name,
                    size_bytes=int(tm["file_size"] or 0),
                    outcome=(
                        MemberOutcome.SKIPPED
                        if tm["is_dir"] or tm["is_symlink"]
                        else MemberOutcome.PENDING
                    ),
                    skip_reason=("directory" if tm["is_dir"] else "symlink" if tm["is_symlink"] else None),
                    is_symlink=bool(tm["is_symlink"]),
                    is_directory=bool(tm["is_dir"]),
                )
                self.ingestion.upsert_member(mm)
            self._mark_container_source(source, detection, meta={**meta, **signals})

        # Process pending by extracting each
        while True:
            if self.ingestion.is_cancel_requested(source.source_id):
                self.ingestion.upsert_container(
                    container_source_id=source.source_id,
                    project_id=source.project_id,
                    phase=IngestionPhase.CANCELLED,
                )
                return self.get_progress(source.source_id)
            batch = self.ingestion.list_pending_members(source.source_id, limit=50)
            if not batch:
                break
            for member in batch:
                skip, skip_reason = should_skip_path(
                    member.relative_path,
                    enabled=self.settings.code_repo_ignore_defaults,
                )
                if skip:
                    member.outcome = MemberOutcome.SKIPPED
                    member.skip_reason = skip_reason
                    member.parse_status = "skipped"
                    self.ingestion.upsert_member(member)
                    continue
                try:
                    dest, content_hash, size = extract_tar_member(
                        raw_path,
                        member.relative_path,  # may fail if raw name differs
                        relative_path=member.relative_path,
                        staging_root=staging,
                        settings=self.settings,
                    )
                except Exception:
                    # Try with original path from metadata — fall back fail
                    try:
                        dest, content_hash, size = extract_tar_member(
                            raw_path,
                            member.relative_path,
                            relative_path=member.relative_path,
                            staging_root=staging,
                            settings=self.settings,
                        )
                    except Exception as exc:  # noqa: BLE001
                        member.outcome = MemberOutcome.FAILED
                        member.error_code = "TAR_EXTRACT_FAILED"
                        member.skip_reason = redact_secrets(str(exc))[:200]
                        member.parse_status = "failed"
                        self.ingestion.upsert_member(member)
                        continue
                member.content_hash = content_hash
                member.size_bytes = size
                sample = sample_file_prefix(dest)
                detection_m = detect_source_type(
                    filename=member.relative_path,
                    sample=sample,
                    allow_unknown_text=self.settings.allow_unknown_text,
                )
                child = self._ensure_child_source(parent=source, member=member, detection=detection_m, raw_path=dest)
                handler = self.registry.resolve(detection_m, filename=member.relative_path)
                if handler is None:
                    member.outcome = MemberOutcome.SKIPPED
                    member.skip_reason = "unsupported"
                    member.child_source_id = child.source_id
                    self.ingestion.upsert_member(member)
                    continue
                artifact = handler.ingest(
                    dest,
                    detection=detection_m,
                    relative_path=member.relative_path,
                    settings=self.settings,
                )
                self._apply_child_artifact(source, child, member, detection_m, artifact)
        return self._finalize_container(source.source_id)

    def _process_gzip_single(
        self,
        source: ResearchSource,
        raw_path: Path,
        detection: Any,
        staging: Path,
        *,
        nested_depth: int,
    ) -> IngestionProgress:
        name = source.title or raw_path.name
        out_name = name[:-3] if name.lower().endswith(".gz") else name + ".out"
        dest, content_hash, size = decompress_gzip_single(
            raw_path,
            staging_root=staging,
            output_name=out_name,
            settings=self.settings,
        )
        sample = sample_file_prefix(dest)
        inner = detect_source_type(
            filename=out_name,
            sample=sample,
            allow_unknown_text=self.settings.allow_unknown_text,
        )
        handler = self.registry.resolve(inner, filename=out_name)
        if handler is None:
            self._save_source_state(
                source,
                parse_status=ParseStatus.SKIPPED,
                brain_status=BrainStatus.SKIPPED,
                parser="gzip",
                text="",
                detection=detection,
                extra_meta={"skip_reason": "unsupported_after_gunzip"},
            )
            self.ingestion.upsert_container(
                container_source_id=source.source_id,
                project_id=source.project_id,
                phase=IngestionPhase.COMPLETED,
            )
            return self.get_progress(source.source_id)
        artifact = handler.ingest(
            dest,
            detection=inner,
            relative_path=out_name,
            settings=self.settings,
        )
        return self._finalize_artifact(source, artifact, inner, is_child=False)

    def _apply_child_artifact(
        self,
        parent: ResearchSource,
        child: ResearchSource,
        member: ManifestMember,
        detection: Any,
        artifact: NormalizedArtifact,
    ) -> None:
        member.parser = artifact.parser
        if artifact.outcome == MemberOutcome.ROUTED:
            self._route_dataset(child, artifact)
            member.outcome = MemberOutcome.ROUTED
            member.skip_reason = artifact.skip_reason
            member.parse_status = "skipped"
            member.child_source_id = child.source_id
            self.ingestion.upsert_member(member)
            return
        if artifact.outcome != MemberOutcome.SUCCESS:
            member.outcome = artifact.outcome
            member.skip_reason = artifact.skip_reason
            member.error_code = artifact.error_code
            member.parse_status = "failed" if artifact.outcome == MemberOutcome.FAILED else "skipped"
            member.child_source_id = child.source_id
            self.ingestion.upsert_member(member)
            return
        text = artifact.content.read_text()
        snap = self._write_snapshot(parent.project_id, child.source_id, text)
        updated = self._save_source_state(
            child,
            parse_status=ParseStatus.OK,
            brain_status=BrainStatus.PENDING,
            parser=artifact.parser,
            text=text,
            detection=detection,
            artifact=artifact,
            snapshot_path=str(snap),
            archive_filename=parent.title,
            parent_source_id=parent.source_id,
            container_source_id=parent.source_id,
            content_hash_override=artifact.content_hash,
        )
        synced = self._brain_sync(updated, text, artifact=artifact)
        member.outcome = MemberOutcome.SUCCESS
        member.parse_status = "ok"
        member.brain_status = synced.brain_status.value
        member.brain_document_id = synced.brain_document_id
        member.child_source_id = synced.source_id
        self.ingestion.upsert_member(member)

    def _finalize_container(self, container_source_id: str) -> IngestionProgress:
        manifest = self.ingestion.build_manifest(container_source_id)
        phase = manifest.aggregate_phase()
        if self.ingestion.is_cancel_requested(container_source_id):
            phase = IngestionPhase.CANCELLED
        container = self.ingestion.get_container(container_source_id)
        self.ingestion.upsert_container(
            container_source_id=container_source_id,
            project_id=str((container or {}).get("project_id") or ""),
            phase=phase,
            compressed_bytes=manifest.compressed_bytes,
            uncompressed_bytes=manifest.total_uncompressed_bytes,
            progress=manifest.public_dict(include_members=False),
            manifest_meta=manifest.metadata,
        )
        # Update parent research source aggregate
        parent = self.research.get_source(container_source_id)
        if parent is not None:
            prov = dict(parent.provenance or {})
            prov["ingestion"] = manifest.public_dict(include_members=False)
            prov["ingestion_phase"] = phase.value
            meta = dict(parent.metadata or {})
            meta["is_container"] = True
            meta["ingestion_phase"] = phase.value
            parse = ParseStatus.OK
            if phase == IngestionPhase.FAILED:
                parse = ParseStatus.FAILED
            elif phase == IngestionPhase.CANCELLED:
                parse = ParseStatus.SKIPPED
            updated = ResearchSource(
                source_id=parent.source_id,
                project_id=parent.project_id,
                source_type=parent.source_type,
                created_at=parent.created_at,
                original_uri=parent.original_uri,
                canonical_uri=parent.canonical_uri,
                title=parent.title,
                author=parent.author,
                published_at=parent.published_at,
                fetched_at=parent.fetched_at,
                content_hash=parent.content_hash,
                mime_type=parent.mime_type,
                snapshot_path=parent.snapshot_path,
                parse_status=parse,
                parser=parent.parser or "archive",
                brain_status=BrainStatus.NOT_APPLICABLE,
                brain_document_id=parent.brain_document_id,
                brain_error=parent.brain_error,
                provenance=prov,
                metadata=meta,
            )
            self.research.save_source(updated)
        event = "ingestion_completed"
        if phase == IngestionPhase.PARTIAL:
            event = "ingestion_partial"
        elif phase == IngestionPhase.FAILED:
            event = "ingestion_failed"
        elif phase == IngestionPhase.CANCELLED:
            event = "ingestion_cancelled"
        self._event(event, phase.value, {"source_id": container_source_id})
        return self.get_progress(container_source_id)

    def _mark_container_source(self, source: ResearchSource, detection: Any, meta: dict[str, Any]) -> None:
        prov = dict(source.provenance or {})
        prov["detection"] = detection.public_dict() if hasattr(detection, "public_dict") else {}
        prov["archive"] = meta
        md = dict(source.metadata or {})
        md["is_container"] = True
        md["ingestion_phase"] = IngestionPhase.EXPANDING.value
        updated = ResearchSource(
            source_id=source.source_id,
            project_id=source.project_id,
            source_type=source.source_type,
            created_at=source.created_at,
            original_uri=source.original_uri,
            canonical_uri=source.canonical_uri,
            title=source.title,
            author=source.author,
            published_at=source.published_at,
            fetched_at=source.fetched_at,
            content_hash=source.content_hash,
            mime_type=source.mime_type or "application/zip",
            snapshot_path=source.snapshot_path,
            parse_status=ParseStatus.PENDING,
            parser="archive",
            brain_status=BrainStatus.NOT_APPLICABLE,
            brain_document_id=None,
            brain_error=None,
            provenance=prov,
            metadata=md,
        )
        self.research.save_source(updated)

    def _ensure_child_source(
        self,
        *,
        parent: ResearchSource,
        member: ManifestMember,
        detection: Any,
        raw_path: Path,
    ) -> ResearchSource:
        # Idempotent: reuse existing child for same container+path
        for existing in self.research.list_sources(parent.project_id, limit=2000):
            prov = existing.provenance or {}
            if (
                prov.get("container_source_id") == parent.source_id
                and prov.get("relative_path") == member.relative_path
            ):
                return existing

        source_id = str(uuid.uuid4())
        child = ResearchSource(
            source_id=source_id,
            project_id=parent.project_id,
            source_type=SourceType.LOCAL_FILE,
            original_uri=f"archive://{parent.title}/{member.relative_path}",
            canonical_uri=f"archive://{parent.project_id}/{parent.source_id}/{member.relative_path}",
            title=member.original_filename,
            fetched_at=utc_now(),
            content_hash=member.content_hash,
            mime_type=detection.mime_type if hasattr(detection, "mime_type") else member.mime_type,
            snapshot_path=None,
            parse_status=ParseStatus.PENDING,
            parser=None,
            brain_status=BrainStatus.PENDING,
            provenance={
                "parent_source_id": parent.source_id,
                "container_source_id": parent.source_id,
                "archive_filename": parent.title,
                "relative_path": member.relative_path,
                "original_filename": member.original_filename,
                "raw_path": str(raw_path),
                "size_bytes": member.size_bytes,
                "detection": detection.public_dict() if hasattr(detection, "public_dict") else {},
                "project_id": parent.project_id,
                "research_source_id": source_id,
            },
            metadata={"is_child": True, "upload": True},
            created_at=utc_now(),
        )
        # Insert without content_hash global dedupe collision across paths:
        # temporarily clear hash for insert if collision would drop the child.
        stored = self.research.upsert_source(child)
        if stored.source_id != child.source_id:
            # Collision on content_hash — create with unique canonical and no hash first
            child = ResearchSource(
                source_id=source_id,
                project_id=parent.project_id,
                source_type=SourceType.LOCAL_FILE,
                original_uri=child.original_uri,
                canonical_uri=child.canonical_uri,
                title=child.title,
                fetched_at=child.fetched_at,
                content_hash=None,
                mime_type=child.mime_type,
                snapshot_path=None,
                parse_status=ParseStatus.PENDING,
                parser=None,
                brain_status=BrainStatus.PENDING,
                provenance=dict(child.provenance),
                metadata={**dict(child.metadata), "content_hash_deferred": member.content_hash},
                created_at=child.created_at,
            )
            stored = self.research.upsert_source(child)
        return stored

    def _write_snapshot(self, project_id: str, source_id: str, text: str) -> Path:
        snap_dir = ensure_dir(self.snapshots_root / project_id)
        snapshot = snap_dir / f"{source_id}.txt"
        atomic_write_text(snapshot, text)
        return snapshot

    def _save_source_state(
        self,
        source: ResearchSource,
        *,
        parse_status: ParseStatus,
        brain_status: BrainStatus,
        parser: str | None,
        text: str,
        detection: Any,
        artifact: NormalizedArtifact | None = None,
        snapshot_path: str | None = None,
        archive_filename: str | None = None,
        parent_source_id: str | None = None,
        container_source_id: str | None = None,
        content_hash_override: str | None = None,
        extra_meta: dict[str, Any] | None = None,
        brain_error: str | None = None,
    ) -> ResearchSource:
        prov = dict(source.provenance or {})
        if hasattr(detection, "public_dict"):
            prov["detection"] = detection.public_dict()
        if artifact is not None:
            prov["parser"] = artifact.parser
            prov["parser_version"] = artifact.parser_version
            prov["content_hash"] = artifact.content_hash
            prov.update(artifact.provenance)
            if artifact.structured_metadata:
                prov["structure"] = artifact.structured_metadata
            if artifact.error_code:
                prov["error_code"] = artifact.error_code
            if artifact.skip_reason:
                prov["skip_reason"] = artifact.skip_reason
        if archive_filename:
            prov["archive_filename"] = archive_filename
        if parent_source_id:
            prov["parent_source_id"] = parent_source_id
        if container_source_id:
            prov["container_source_id"] = container_source_id
        if text:
            prov["text_hash"] = sha256_text(text)
        meta = dict(source.metadata or {})
        if extra_meta:
            meta.update(extra_meta)
        if artifact is not None:
            meta["structure"] = artifact.structured_metadata
            meta["warnings"] = artifact.warnings
            meta["unsupported_features"] = artifact.unsupported_features
            if artifact.error_code:
                meta["error_code"] = artifact.error_code
            if artifact.skip_reason:
                meta["skip_reason"] = artifact.skip_reason
            if artifact.route_target:
                meta["route_target"] = artifact.route_target
        updated = ResearchSource(
            source_id=source.source_id,
            project_id=source.project_id,
            source_type=source.source_type,
            created_at=source.created_at,
            original_uri=source.original_uri,
            canonical_uri=source.canonical_uri,
            title=source.title,
            author=source.author,
            published_at=source.published_at,
            fetched_at=source.fetched_at,
            content_hash=content_hash_override or (artifact.content_hash if artifact else source.content_hash),
            mime_type=source.mime_type or (detection.mime_type if hasattr(detection, "mime_type") else None),
            snapshot_path=snapshot_path if snapshot_path is not None else source.snapshot_path,
            parse_status=parse_status,
            parser=parser,
            brain_status=brain_status,
            brain_document_id=source.brain_document_id,
            brain_error=brain_error,
            provenance=prov,
            metadata=meta,
        )
        return self.research.save_source(updated)

    def _brain_sync(
        self,
        source: ResearchSource,
        text: str,
        *,
        artifact: NormalizedArtifact | None = None,
    ) -> ResearchSource:
        if self.knowledge is None:
            return self._mark_brain(source, BrainStatus.FAILED, error="KnowledgeStore unavailable")
        if source.parse_status != ParseStatus.OK or not (text or "").strip():
            return self._mark_brain(source, BrainStatus.SKIPPED, error="No parseable text")

        content_hash = source.content_hash or sha256_text(text)
        doc_id = f"research-upload:{content_hash}"
        prov = source.provenance or {}
        trust = {
            "trust": "user_supplied",
            "source": "research_upload",
            "project_id": source.project_id,
            "research_source_id": source.source_id,
            "filename": source.title,
            "mime_type": source.mime_type,
            "content_hash": content_hash,
            "parser": source.parser,
            "parser_version": (artifact.parser_version if artifact else PARSER_VERSION),
            "container_source_id": prov.get("container_source_id"),
            "parent_source_id": prov.get("parent_source_id"),
            "archive_filename": prov.get("archive_filename"),
            "relative_path": prov.get("relative_path"),
            "original_path": prov.get("relative_path") or source.original_uri,
        }
        # Page/slide/sheet provenance when present
        for key in ("page_count", "pages", "slides", "sheets", "locations", "language", "module_path"):
            if key in prov:
                trust[key] = prov[key]
        try:
            record = self.knowledge.upsert_document(
                document_id=doc_id,
                title=self._brain_title(source),
                content=text,
                source="research_upload",
                original_path=str(prov.get("relative_path") or source.original_uri),
                size_bytes=len(text.encode("utf-8")),
                parser=source.parser or "source_ingestion",
                source_type="research_upload",
                trust_metadata=trust,
            )
            return self._mark_brain(
                source,
                BrainStatus.SYNCED,
                document_id=record.id if hasattr(record, "id") else doc_id,
            )
        except Exception as exc:  # noqa: BLE001
            return self._mark_brain(source, BrainStatus.FAILED, error=redact_secrets(str(exc))[:500])

    def _brain_title(self, source: ResearchSource) -> str:
        prov = source.provenance or {}
        archive = prov.get("archive_filename")
        rel = prov.get("relative_path")
        if archive and rel:
            return f"{archive}/{rel}"
        return source.title or "Research upload"

    def _mark_brain(
        self,
        source: ResearchSource,
        status: BrainStatus,
        *,
        document_id: str | None = None,
        error: str | None = None,
    ) -> ResearchSource:
        updated = ResearchSource(
            source_id=source.source_id,
            project_id=source.project_id,
            source_type=source.source_type,
            created_at=source.created_at,
            original_uri=source.original_uri,
            canonical_uri=source.canonical_uri,
            title=source.title,
            author=source.author,
            published_at=source.published_at,
            fetched_at=source.fetched_at,
            content_hash=source.content_hash,
            mime_type=source.mime_type,
            snapshot_path=source.snapshot_path,
            parse_status=source.parse_status,
            parser=source.parser,
            brain_status=status,
            brain_document_id=document_id if document_id is not None else source.brain_document_id,
            brain_error=error,
            provenance=dict(source.provenance),
            metadata=dict(source.metadata),
        )
        return self.research.save_source(updated)

    def _route_dataset(self, source: ResearchSource, artifact: NormalizedArtifact) -> None:
        if self.dataset_service is None:
            return
        raw = (artifact.provenance or {}).get("raw_path")
        if not raw:
            return
        try:
            # Best-effort: enqueue local import if API exists
            enqueue = getattr(self.dataset_service, "enqueue_import_local", None)
            if callable(enqueue):
                enqueue(path=str(raw), label=source.title or Path(str(raw)).name)
        except Exception:  # noqa: BLE001
            pass

    def retry_failed_children(self, container_source_id: str) -> IngestionProgress:
        members = self.ingestion.list_members(container_source_id, limit=2000)
        for m in members:
            if m.outcome == MemberOutcome.FAILED:
                m.outcome = MemberOutcome.PENDING
                m.error_code = None
                m.skip_reason = None
                m.parse_status = "pending"
                self.ingestion.upsert_member(m)
        self.ingestion.upsert_container(
            container_source_id=container_source_id,
            project_id=(self.ingestion.get_container(container_source_id) or {}).get("project_id") or "",
            phase=IngestionPhase.QUEUED,
        )
        return self.process_source(container_source_id)

    def retry_brain_only(self, container_source_id: str) -> IngestionProgress:
        for member in self.ingestion.list_brain_retry_members(container_source_id, limit=500):
            if not member.child_source_id:
                continue
            child = self.research.get_source(member.child_source_id)
            if child is None or not child.snapshot_path:
                continue
            text = Path(child.snapshot_path).read_text(encoding="utf-8")
            synced = self._brain_sync(child, text)
            member.brain_status = synced.brain_status.value
            member.brain_document_id = synced.brain_document_id
            self.ingestion.upsert_member(member)
        return self._finalize_container(container_source_id)

    def get_progress(self, source_id: str) -> IngestionProgress:
        container = self.ingestion.get_container(source_id)
        counts = self.ingestion.count_members(source_id)
        total = int(counts.get("total") or 0)
        done = total - int(counts.get("pending") or 0)
        phase_raw = (container or {}).get("phase") or IngestionPhase.STORED.value
        try:
            phase = IngestionPhase(str(phase_raw))
        except ValueError:
            phase = IngestionPhase.STORED
        progress_pct: float | None
        if total <= 0:
            progress_pct = None if phase not in {
                IngestionPhase.COMPLETED,
                IngestionPhase.PARTIAL,
                IngestionPhase.FAILED,
                IngestionPhase.CANCELLED,
                IngestionPhase.QUARANTINED,
            } else 100.0
        else:
            progress_pct = round(100.0 * done / total, 2)
        return IngestionProgress(
            source_id=source_id,
            job_id=(container or {}).get("job_id"),
            status=phase,
            phase=phase,
            progress_pct=progress_pct,
            files_discovered=total,
            files_ingested=int(counts.get("success") or 0),
            files_skipped=int(counts.get("skipped") or 0),
            files_failed=int(counts.get("failed") or 0),
            files_pending=int(counts.get("pending") or 0),
            files_quarantined=int(counts.get("quarantined") or 0),
            files_duplicate=int(counts.get("duplicate") or 0),
            files_routed=int(counts.get("routed") or 0),
            brain_synced=int(counts.get("brain_synced") or 0),
            brain_failed=int(counts.get("brain_failed") or 0),
            bytes_processed=int((container or {}).get("uncompressed_bytes") or 0),
            compressed_bytes=(container or {}).get("compressed_bytes"),
            uncompressed_bytes=(container or {}).get("uncompressed_bytes"),
            archive_type=(container or {}).get("archive_type"),
            filename=(container or {}).get("filename"),
            error=(container or {}).get("error"),
            cancel_requested=bool((container or {}).get("cancel_requested")),
        )

    def _finalize_phase(self, source_id: str, phase: IngestionPhase) -> IngestionProgress:
        container = self.ingestion.get_container(source_id)
        self.ingestion.upsert_container(
            container_source_id=source_id,
            project_id=str((container or {}).get("project_id") or ""),
            phase=phase,
        )
        return self.get_progress(source_id)
