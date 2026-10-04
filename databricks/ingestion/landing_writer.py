"""Immutable JSONL batches plus commit markers for local and UC-volume replay.

Remote file moves can be copy/delete. Bronze watches only *.ready.json markers,
published AFTER the final upload returns, never partially written JSONL paths.
Failed publication leaves audit files but no consumable marker; retry is idempotent.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Protocol

from contracts.models import NormalizedEvent


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError(f"unsafe path identifier: {value!r}")
    return value


class Store(Protocol):
    def put_immutable(self, path: str, data: bytes) -> None: ...


class LocalStore:
    """Same-filesystem atomic publication; a matching retry never overwrites."""
    def put_immutable(self, path: str, data: bytes) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".staging-", delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if destination.read_bytes() != data:
                    raise FileExistsError(f"immutable batch collision at {destination}")
        finally:
            temporary.unlink(missing_ok=True)


class SDKStore:
    """Databricks Files API; credentials come from SDK auth, never source files."""
    def __init__(self, workspace_client=None):
        if workspace_client is None:
            from databricks.sdk import WorkspaceClient
            workspace_client = WorkspaceClient()
        self.client = workspace_client

    def put_immutable(self, path: str, data: bytes) -> None:
        from databricks.sdk.errors import AlreadyExists, NotFound
        if not path.startswith("/Volumes/"):
            raise ValueError("SDKStore requires a /Volumes/ path")
        self.client.files.create_directory(str(Path(path).parent))
        try:
            self.client.files.get_metadata(path)
        except NotFound:
            try:
                self.client.files.upload(path, io.BytesIO(data), overwrite=False)
                return
            except AlreadyExists:
                pass
        download = self.client.files.download(path)
        with download.contents as stream:
            existing = stream.read()
        if existing != data:
            raise FileExistsError(f"immutable batch collision at {path}")


class LandingWriter:
    def __init__(self, root: str | Path, store: Store | None = None):
        self.root = str(root).rstrip("/")
        self.store = store or LocalStore()

    def publish(self, run_id: str, signal: str, batch_number: int, events: list[dict]) -> dict:
        identifier(run_id)
        identifier(signal)
        if signal not in {"hr", "eda", "acc", "ibi", "temp"} or batch_number < 0 or not events:
            raise ValueError("nonempty batch, supported signal and nonnegative batch number required")
        # Preserve ingested_at across retries by leaving stamping to the event source.
        # The replay controller stamps when a batch first becomes ready to publish.
        normalized = []
        for row in events:
            metadata = {key: row[key] for key in ("source_file", "source_row") if key in row}
            event = NormalizedEvent.model_validate({k: v for k, v in row.items() if k not in metadata})
            if event.run_id != run_id or event.signal != signal:
                raise ValueError("event run_id/signal does not match destination")
            if set(metadata) != {"source_file", "source_row"} or not isinstance(metadata["source_row"], int) or metadata["source_row"] < 1:
                raise ValueError("Bronze rows require source_file and positive integer source_row")
            normalized.append({**event.model_dump(mode="json"), **metadata})
        payload = b"".join((json.dumps(row, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
                           for row in normalized)
        directory = f"{self.root}/{run_id}/{signal}"
        path = f"{directory}/batch-{batch_number:09d}.jsonl"
        digest = hashlib.sha256(payload).hexdigest()
        # Stage outside the watched *.ready.json pattern. Keep immutable staging
        # artifacts for audit; no copy/delete operation is treated as atomic.
        self.store.put_immutable(f"{directory}/.staging/{digest}.jsonl", payload)
        self.store.put_immutable(path, payload)
        marker = {"path": path, "sha256": digest, "row_count": len(events),
                  "run_id": run_id, "signal": signal}
        self.store.put_immutable(path.removesuffix(".jsonl") + ".ready.json",
                                 (json.dumps(marker, sort_keys=True) + "\n").encode())
        return marker
