"""Bounded offline search over an extracted official Godot documentation tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
from typing import Any, Iterable, Sequence

from gameloop.locations import PROJECT_ROOT


MAX_FILE_BYTES = 2 * 1024 * 1024
DEFAULT_LIMIT = 8
SUPPORTED_SUFFIXES = {".txt", ".rst", ".md", ".html"}


class GodotDocsError(RuntimeError):
    pass


def docs_root(explicit: str | Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("GAMELOOP_GODOT_DOCS_ROOT"):
        candidates.append(Path(os.environ["GAMELOOP_GODOT_DOCS_ROOT"]))
    candidates.extend(
        (
            PROJECT_ROOT / "tools" / "godot-docs-root",
            PROJECT_ROOT / "docs" / "vendor" / "godot-docs-html",
        )
    )
    for candidate in candidates:
        resolved = candidate.expanduser().resolve(strict=False)
        if resolved.is_dir():
            return resolved
    checked = ", ".join(str(path.expanduser()) for path in candidates) or "none"
    raise GodotDocsError(
        "official Godot documentation directory is unavailable; checked: " + checked
    )


def search_docs(
    query: str,
    *,
    root: Path,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    terms = tuple(re.findall(r"[A-Za-z0-9_]+", query.lower()))
    if not terms:
        raise GodotDocsError("search query must contain a word or symbol")
    if not 1 <= limit <= 30:
        raise GodotDocsError("search limit must be between 1 and 30")

    index = docs_index(root)
    if index.is_file():
        indexed = _search_index(query, terms=terms, root=root, index=index, limit=limit)
        if indexed is not None:
            return indexed

    matches: list[dict[str, Any]] = []
    for path in _candidate_files(root, terms):
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lowered = text.lower()
        positions = [lowered.find(term) for term in terms]
        if any(position < 0 for position in positions):
            continue
        score = sum(lowered.count(term) for term in terms)
        first = min(positions)
        line_number = text.count("\n", 0, first) + 1
        lines = text.splitlines()
        start = max(0, line_number - 2)
        excerpt = "\n".join(lines[start : start + 5]).strip()
        matches.append(
            {
                "source": path.relative_to(root).as_posix(),
                "line": line_number,
                "score": score,
                "excerpt": excerpt[:1200],
                "source_sha256": _sha256(path),
            }
        )
    matches.sort(key=lambda item: (-item["score"], item["source"], item["line"]))
    return {
        "schema_version": 1,
        "tool": "godot-docs",
        "mode": "offline-official-corpus",
        "query": query,
        "root": str(root),
        "results": matches[:limit],
        "result_count": min(len(matches), limit),
    }


def lookup_symbol(
    symbol: str,
    *,
    root: Path,
    limit: int = 5,
) -> dict[str, Any]:
    normalized = symbol.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:]*", normalized):
        raise GodotDocsError("lookup expects a Godot class or class.member symbol")
    result = search_docs(normalized.replace("::", "."), root=root, limit=limit)
    result["operation"] = "lookup"
    result["symbol"] = normalized
    return result


def doctor(*, root: Path) -> dict[str, Any]:
    files = list(_source_files(root))
    index = docs_index(root)
    return {
        "schema_version": 1,
        "tool": "godot-docs",
        "status": "ready" if files else "blocked",
        "mode": "offline-official-corpus",
        "root": str(root),
        "source_files": len(files),
        "index": str(index),
        "index_ready": index.is_file(),
        "network_access": False,
    }


def docs_index(root: Path, explicit: str | Path | None = None) -> Path:
    configured = explicit or os.environ.get("GAMELOOP_GODOT_DOCS_INDEX")
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    return root / ".gameloop-godot-docs.sqlite3"


def build_index(*, root: Path, index: Path) -> dict[str, Any]:
    index.parent.mkdir(parents=True, exist_ok=True)
    temporary = index.with_name(f".{index.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    chunks = 0
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE chunks USING fts5("
            "source_path UNINDEXED, html_path UNINDEXED, title, section, content, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        connection.execute(
            "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        for path in _index_source_files(root):
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            relative = path.relative_to(root).as_posix()
            title = path.stem
            for section_index, content in enumerate(_text_chunks(text), 1):
                connection.execute(
                    "INSERT INTO chunks(source_path, html_path, title, section, content) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (relative, "", title, f"chunk-{section_index}", content),
                )
                chunks += 1
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            (
                ("schema_version", "1"),
                ("root", str(root)),
                ("chunks", str(chunks)),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    os.replace(temporary, index)
    return {
        "schema_version": 1,
        "tool": "godot-docs",
        "status": "ready",
        "operation": "index",
        "root": str(root),
        "index": str(index),
        "chunks": chunks,
        "network_access": False,
    }


def role_guidance(role: str) -> str:
    responsibility = {
        "planner": "Check uncertain Godot APIs before freezing an acceptance plan.",
        "developer": "Check uncertain Godot APIs after parse/import/runtime errors instead of guessing.",
        "tester": "Check engine-behavior claims when needed, but judge the actual candidate evidence.",
    }.get(role, "Use documentation only for engine semantics.")
    return (
        "## Offline Godot documentation\n\n"
        "The `gameloop-godot-docs` command searches only the configured local copy "
        "of the official Godot documentation; it performs no network requests. "
        f"{responsibility} Use `gameloop-godot-docs search '<query>'` or "
        "`gameloop-godot-docs lookup Class.member`. Documentation is not proof that "
        "the candidate implements or visibly demonstrates a behavior.\n"
    )


def _source_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            yield path


def _candidate_files(root: Path, terms: tuple[str, ...]) -> Iterable[Path]:
    """Use ripgrep as a fast locator, with a pure-Python fallback."""

    ripgrep = shutil.which("rg")
    if ripgrep is None:
        yield from _source_files(root)
        return
    command = [
        ripgrep,
        "-l",
        "-i",
        "--fixed-strings",
        "--glob",
        "*.txt",
        "--glob",
        "*.rst",
        "--glob",
        "*.md",
        "--glob",
        "*.html",
        "--",
        terms[0],
        str(root),
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode not in {0, 1}:
        yield from _source_files(root)
        return
    paths = {
        Path(line).resolve(strict=False)
        for line in result.stdout.splitlines()
        if line.strip()
    }
    for path in sorted(paths):
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if path.is_file() and not path.is_symlink():
            yield path


def _index_source_files(root: Path) -> Iterable[Path]:
    rst_sources = root / "_sources"
    if rst_sources.is_dir():
        yield from (
            path
            for path in sorted(rst_sources.rglob("*.rst.txt"))
            if path.is_file() and not path.is_symlink()
        )
        return
    yield from _source_files(root)


def _text_chunks(text: str, *, size: int = 6000) -> Iterable[str]:
    paragraphs = re.split(r"\n\s*\n", text)
    current: list[str] = []
    length = 0
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if current and length + len(paragraph) + 2 > size:
            yield "\n\n".join(current)
            current = []
            length = 0
        current.append(paragraph)
        length += len(paragraph) + 2
    if current:
        yield "\n\n".join(current)


def _search_index(
    query: str,
    *,
    terms: tuple[str, ...],
    root: Path,
    index: Path,
    limit: int,
) -> dict[str, Any] | None:
    expression = " AND ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
    try:
        connection = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
        rows = connection.execute(
            "SELECT source_path, title, section, content, bm25(chunks) "
            "FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks) LIMIT ?",
            (expression, limit),
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        if "connection" in locals():
            connection.close()
    results = []
    for source, title, section, content, rank in rows:
        source_path = root / str(source)
        results.append(
            {
                "source": str(source),
                "line": None,
                "score": round(float(-rank), 6),
                "title": str(title),
                "section": str(section),
                "excerpt": str(content)[:1200],
                "source_sha256": _sha256(source_path) if source_path.is_file() else None,
            }
        )
    return {
        "schema_version": 1,
        "tool": "godot-docs",
        "mode": "offline-official-corpus-index",
        "query": query,
        "root": str(root),
        "index": str(index),
        "results": results,
        "result_count": len(results),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Extracted official Godot documentation root")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor")
    index = subparsers.add_parser("index")
    index.add_argument("--output")
    search = subparsers.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    lookup = subparsers.add_parser("lookup")
    lookup.add_argument("symbol")
    lookup.add_argument("--limit", type=int, default=5)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = docs_root(args.root)
        if args.command == "doctor":
            payload = doctor(root=root)
        elif args.command == "index":
            payload = build_index(root=root, index=docs_index(root, args.output))
        elif args.command == "search":
            payload = search_docs(args.query, root=root, limit=args.limit)
        elif args.command == "lookup":
            payload = lookup_symbol(args.symbol, root=root, limit=args.limit)
        else:
            raise AssertionError(args.command)
    except GodotDocsError as error:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "tool": "godot-docs",
                    "status": "blocked",
                    "error": str(error),
                },
                sort_keys=True,
            )
        )
        return 3
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
