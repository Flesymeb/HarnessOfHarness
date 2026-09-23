"""Local-only asset pool contracts used by benchmark adapters."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
from typing import Any, Iterable


class AssetPoolError(ValueError):
    pass


@dataclass(frozen=True)
class AssetRecord:
    relative_path: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


class LocalAssetPool:
    """Read a caller-provided asset directory without network discovery."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        if not self.root.is_dir():
            raise AssetPoolError(f"asset pool directory does not exist: {self.root}")

    def query(
        self,
        terms: Iterable[str],
        *,
        limit: int = 40,
    ) -> list[AssetRecord]:
        if not 1 <= limit <= 200:
            raise AssetPoolError("asset query limit must be between 1 and 200")
        needles = tuple(term.strip().lower() for term in terms if term.strip())
        records: list[AssetRecord] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(self.root).as_posix()
            if needles and not all(needle in relative.lower() for needle in needles):
                continue
            records.append(self._record(path))
            if len(records) >= limit:
                break
        return records

    def materialize(
        self,
        relative_path: str,
        *,
        destination_root: Path,
        destination_path: str,
    ) -> dict[str, Any]:
        source = self._contained_path(self.root, relative_path, label="asset")
        if not source.is_file() or source.is_symlink():
            raise AssetPoolError(f"asset is not a regular file: {relative_path}")
        destination_root = destination_root.expanduser().resolve()
        destination_root.mkdir(parents=True, exist_ok=True)
        destination = self._contained_path(
            destination_root,
            destination_path,
            label="destination",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        record = self._record(source)
        copied_sha256 = _sha256(destination)
        if copied_sha256 != record.sha256:
            destination.unlink(missing_ok=True)
            raise AssetPoolError("materialized asset hash does not match its source")
        return {
            "schema_version": 1,
            "provider": "local-asset-pool",
            "network_access": False,
            "pool_root": str(self.root),
            "source": record.to_dict(),
            "destination": str(destination),
            "destination_sha256": copied_sha256,
        }

    def manifest(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "provider": "local-asset-pool",
            "root": str(self.root),
            "network_search": False,
            "selection_authority": "developer uses only the caller-provided pool",
        }

    def _record(self, path: Path) -> AssetRecord:
        return AssetRecord(
            relative_path=path.relative_to(self.root).as_posix(),
            size_bytes=path.stat().st_size,
            sha256=_sha256(path),
        )

    @staticmethod
    def _contained_path(root: Path, relative: str, *, label: str) -> Path:
        raw = Path(relative)
        if raw.is_absolute():
            raise AssetPoolError(f"{label} path must be relative")
        resolved = (root / raw).resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise AssetPoolError(f"{label} path escapes its root: {relative}") from error
        return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
