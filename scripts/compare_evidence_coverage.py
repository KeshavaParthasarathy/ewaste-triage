#!/usr/bin/env python3
"""Compare canonical evidence-coverage reports and atomically write the change."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evidence_coverage import (
    CoverageError,
    compare_coverage,
    coverage_json_bytes,
    validate_coverage_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compare_evidence_coverage.py",
        usage="%(prog)s --current PATH (--previous PATH | --initial) --out PATH",
        allow_abbrev=False,
    )
    parser.add_argument("--current", required=True, metavar="PATH", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--previous", metavar="PATH", type=Path)
    mode.add_argument("--initial", action="store_true")
    parser.add_argument("--out", required=True, metavar="PATH", type=Path)
    return parser


def _read_canonical_report(path: Path) -> Mapping[str, object]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CoverageError(f"cannot read coverage report {path}: {exc}") from exc
    try:
        parsed = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoverageError(f"coverage report is not valid UTF-8 JSON: {path}") from exc
    validate_coverage_report(parsed)
    if coverage_json_bytes(parsed) != data:
        raise CoverageError(f"coverage report is not canonical: {path}")
    return parsed


def _paths_alias(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return left.resolve(strict=False) == right.resolve(strict=False)


def _change_json_bytes(change: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            change,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as exc:
        raise CoverageError(f"coverage change is not canonical JSON: {exc}") from exc


def _atomic_write(output: Path, data: bytes) -> None:
    parent = output.parent
    descriptor = -1
    parent_descriptor = -1
    temporary: Path | None = None
    committed = False
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("temporary output is not a regular file")
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        parent_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        os.replace(temporary, output)
        committed = True
        os.fsync(parent_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)
        if temporary is not None and not committed:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        current = _read_canonical_report(arguments.current)
        previous = (
            None
            if arguments.initial
            else _read_canonical_report(arguments.previous)
        )
        inputs = [arguments.current]
        if arguments.previous is not None:
            inputs.append(arguments.previous)
        if any(_paths_alias(arguments.out, path) for path in inputs):
            raise CoverageError("output must not alias an input report")
        change = compare_coverage(previous, current)
        data = _change_json_bytes(change)
        try:
            _atomic_write(arguments.out, data)
        except OSError as exc:
            raise CoverageError(f"cannot write coverage change: {exc}") from exc
    except CoverageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
