#!/usr/bin/env python3
"""Estimate the ZeroPath full-scan size and cost for a local repository.

This script is safe to send to prospective customers. It runs locally, does not
install dependencies, does not call the network, and does not upload code.

Examples:
  python zeropath_scan_cost_estimator.py /path/to/repo
  python zeropath_scan_cost_estimator.py . --include services/api --include packages/core --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

TOKEN_CHARS_DIVISOR = 3
MAX_BYTES_PER_FILE = 1024 * 1024
INITIAL_FULL_SCAN_BASELINE_TOKENS = 8_000_000
INITIAL_FULL_SCAN_BASELINE_COST_USD = Decimal("1500.00")

DEFAULT_CODE_EXTENSIONS = {
    ".bash",
    ".c",
    ".cc",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".fish",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".less",
    ".md",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".scss",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
    ".zsh",
}

DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".idea",
    ".mypy_cache",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    ".vscode",
    "__pycache__",
    "bin",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "obj",
    "out",
    "target",
    "vendor",
    "venv",
}


@dataclass(frozen=True)
class RepositoryEstimate:
    repository_path: str
    included_paths: list[str]
    files_counted: int
    files_skipped: int
    bytes_read: int
    estimated_tokens: int
    estimated_initial_full_scan_cost_usd: str
    pricing_basis: str
    estimate_scope: str


def normalize_extensions(values: Sequence[str] | None) -> set[str]:
    if not values:
        return set(DEFAULT_CODE_EXTENSIONS)

    extensions: set[str] = set()
    for raw_value in values:
        for part in raw_value.split(","):
            extension = part.strip().lower()
            if not extension:
                continue
            extensions.add(extension if extension.startswith(".") else f".{extension}")
    return extensions


def normalize_excluded_dirs(values: Sequence[str] | None) -> set[str]:
    excluded = set(DEFAULT_EXCLUDED_DIRS)
    for raw_value in values or []:
        for part in raw_value.split(","):
            directory_name = part.strip()
            if directory_name:
                excluded.add(directory_name)
    return excluded


def resolve_count_roots(repo_path: Path, include_paths: Sequence[str]) -> list[Path]:
    repo_root = repo_path.resolve()
    if not include_paths:
        return [repo_root]

    roots: list[Path] = []
    for include_path in include_paths:
        candidate = (repo_root / include_path).resolve()
        try:
            candidate.relative_to(repo_root)
        except ValueError as exc:
            raise ValueError(
                f"Included path escapes repository root: {include_path}"
            ) from exc
        if not candidate.is_dir():
            raise ValueError(f"Included path is not a directory: {include_path}")
        if any(candidate == root or candidate.is_relative_to(root) for root in roots):
            continue
        roots = [root for root in roots if not root.is_relative_to(candidate)]
        roots.append(candidate)
    return roots


def iter_candidate_files(
    roots: Iterable[Path],
    *,
    repo_root: Path,
    extensions: set[str],
    excluded_dirs: set[str],
    include_hidden: bool,
) -> Iterable[Path]:
    for count_root in roots:
        for root, dirs, files in os.walk(count_root):
            dirs[:] = [
                directory_name
                for directory_name in dirs
                if directory_name not in excluded_dirs
                and (include_hidden or not directory_name.startswith("."))
            ]

            for file_name in files:
                if not include_hidden and file_name.startswith("."):
                    continue
                file_path = Path(root) / file_name
                if file_path.suffix.lower() not in extensions:
                    continue
                try:
                    file_path.resolve().relative_to(repo_root)
                except ValueError:
                    continue
                yield file_path


def estimate_file_tokens(file_path: Path) -> tuple[int, int] | None:
    try:
        with file_path.open("r", encoding="utf-8", errors="ignore") as handle:
            content = handle.read(MAX_BYTES_PER_FILE)
    except OSError:
        return None

    return len(content) // TOKEN_CHARS_DIVISOR, len(
        content.encode("utf-8", errors="ignore")
    )


def format_usd(value: Decimal) -> str:
    cents = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"${cents:,.2f}"


def estimate_initial_full_scan_cost(estimated_tokens: int) -> str:
    cost = (
        Decimal(estimated_tokens)
        / Decimal(INITIAL_FULL_SCAN_BASELINE_TOKENS)
        * INITIAL_FULL_SCAN_BASELINE_COST_USD
    )
    return format_usd(cost)


def estimate_repository(args: argparse.Namespace) -> RepositoryEstimate:
    repo_path = Path(args.repository).expanduser()
    if not repo_path.is_dir():
        raise ValueError(f"Repository path is not a directory: {repo_path}")

    repo_root = repo_path.resolve()
    roots = resolve_count_roots(repo_root, args.include)
    extensions = normalize_extensions(args.extensions)
    excluded_dirs = normalize_excluded_dirs(args.exclude_dir)

    files_counted = 0
    files_skipped = 0
    bytes_read = 0
    estimated_tokens = 0

    for file_path in iter_candidate_files(
        roots,
        repo_root=repo_root,
        extensions=extensions,
        excluded_dirs=excluded_dirs,
        include_hidden=args.include_hidden,
    ):
        file_estimate = estimate_file_tokens(file_path)
        if file_estimate is None:
            files_skipped += 1
            continue
        file_tokens, file_bytes = file_estimate
        files_counted += 1
        bytes_read += file_bytes
        estimated_tokens += file_tokens

    return RepositoryEstimate(
        repository_path=str(repo_root),
        included_paths=[
            str(root.relative_to(repo_root)) if root != repo_root else "."
            for root in roots
        ],
        files_counted=files_counted,
        files_skipped=files_skipped,
        bytes_read=bytes_read,
        estimated_tokens=estimated_tokens,
        estimated_initial_full_scan_cost_usd=estimate_initial_full_scan_cost(
            estimated_tokens
        ),
        pricing_basis=f"{format_usd(INITIAL_FULL_SCAN_BASELINE_COST_USD)} per {INITIAL_FULL_SCAN_BASELINE_TOKENS:,} estimated tokens",
        estimate_scope="Initial full scan only. Later scans usually use cache and should not use the full repository token amount.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Estimate ZeroPath full-scan repository size and cost without uploading code.",
    )
    parser.add_argument(
        "repository",
        nargs="?",
        default=".",
        help="Path to the local repository to estimate. Defaults to the current directory.",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Repository-relative directory to include. Can be repeated for monorepo partitions.",
    )
    parser.add_argument(
        "--exclude-dir",
        action="append",
        help="Additional directory name to skip. Can be repeated or comma-separated.",
    )
    parser.add_argument(
        "--extensions",
        action="append",
        help="Override counted file extensions. Can be repeated or comma-separated, for example: py,ts,go.",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden files and hidden directories. Hidden paths are skipped by default.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON.",
    )
    return parser


def print_human_readable(estimate: RepositoryEstimate) -> None:
    print("ZeroPath scan cost estimate")
    print(f"Repository: {estimate.repository_path}")
    print(f"Included paths: {', '.join(estimate.included_paths)}")
    print(f"Files counted: {estimate.files_counted:,}")
    if estimate.files_skipped:
        print(
            f"Files skipped because they could not be read: {estimate.files_skipped:,}"
        )
    print(f"Bytes read: {estimate.bytes_read:,}")
    print(f"Estimated repository tokens: {estimate.estimated_tokens:,}")
    print(f"Pricing basis: {estimate.pricing_basis}")
    print(
        f"Estimated initial full scan cost: {estimate.estimated_initial_full_scan_cost_usd}"
    )
    print()
    print(
        "Important: this is only an estimate for the initial full scan. Later scans usually use ZeroPath's cache and should not use the full repository token amount."
    )
    print(
        "Final billing can differ if repository contents, scan scope, or pricing terms change."
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        estimate = estimate_repository(args)
    except ValueError as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(asdict(estimate), indent=2))
    else:
        print_human_readable(estimate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
