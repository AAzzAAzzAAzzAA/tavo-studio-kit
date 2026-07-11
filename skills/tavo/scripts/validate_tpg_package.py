#!/usr/bin/env python3
"""Validate an extracted Tavo plugin package with stdlib-only checks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
URI_OR_DRIVE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
MAX_PLUGIN_FILE_SIZE = 1024 * 1024


@dataclass(frozen=True)
class PackageValidation:
    errors: tuple[str, ...]
    package_dir: Path
    plugin_root: Path | None
    manifest_path: Path | None
    entry_source: str | None
    entry_path: str | None


def is_safe_relative(value: Any) -> bool:
    """Return whether *value* is a canonical package-relative virtual path."""

    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if "\\" in value or "\x00" in value or value.startswith("/") or URI_OR_DRIVE.match(value):
        return False
    segments = value.split("/")
    return all(segment not in {"", ".", ".."} for segment in segments)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _manifest_candidates(package_dir: Path) -> list[Path]:
    return sorted(
        (path for path in package_dir.rglob("manifest.json") if path.is_file() or path.is_symlink()),
        key=lambda path: path.relative_to(package_dir).as_posix(),
    )


def select_plugin_root(package_dir: Path, errors: list[str]) -> tuple[Path | None, Path | None]:
    """Apply Tavo 0.92 manifest selection: root wins, else exactly one nested."""

    root_manifest = package_dir / "manifest.json"
    if root_manifest.is_file() or root_manifest.is_symlink():
        return package_dir, root_manifest

    candidates = [path for path in _manifest_candidates(package_dir) if path != root_manifest]
    if not candidates:
        errors.append("missing manifest.json at package root or in a single wrapping directory")
        return None, None
    if len(candidates) > 1:
        rendered = ", ".join(path.relative_to(package_dir).as_posix() for path in candidates)
        errors.append(f"ambiguous package: multiple nested manifest.json candidates: {rendered}")
        return None, None
    manifest_path = candidates[0]
    return manifest_path.parent, manifest_path


def _validate_resource_path(
    plugin_root: Path,
    value: Any,
    label: str,
    errors: list[str],
    *,
    require_file: bool,
) -> str | None:
    if not is_safe_relative(value):
        errors.append(f"{label} must be a safe package-relative path using forward slashes")
        return None
    assert isinstance(value, str)
    candidate = plugin_root.joinpath(*value.split("/"))
    if not _is_within(candidate, plugin_root):
        errors.append(f"{label} resolves outside the selected plugin root: {value}")
        return None
    if require_file:
        if not candidate.exists():
            errors.append(f"{label} file does not exist: {value}")
            return None
        if not candidate.is_file():
            errors.append(f"{label} must reference a regular file: {value}")
            return None
    return value


def _validate_package_members(plugin_root: Path, errors: list[str]) -> list[Path]:
    safe_files: list[Path] = []
    for path in plugin_root.rglob("*"):
        rel = path.relative_to(plugin_root).as_posix()
        if path.is_symlink():
            if not path.exists():
                errors.append(f"broken symlink is not allowed in plugin package: {rel}")
                continue
            if not _is_within(path, plugin_root):
                errors.append(f"external symlink is not allowed in plugin package: {rel}")
                continue
        if path.is_file():
            if not _is_within(path, plugin_root):
                errors.append(f"plugin file resolves outside the selected plugin root: {rel}")
                continue
            try:
                if path.stat().st_size > MAX_PLUGIN_FILE_SIZE:
                    errors.append(f"unexpectedly large plugin file: {rel}")
            except OSError as exc:
                errors.append(f"could not inspect plugin file {rel}: {exc}")
                continue
            safe_files.append(path)
    return safe_files


def _deduplicate(errors: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(errors))


def validate_package(
    package_dir: Path,
    *,
    require_input_action: bool = False,
    require_html_fragment: bool = False,
    require_marker_text: str = "",
) -> PackageValidation:
    package_dir = package_dir.expanduser().resolve()
    errors: list[str] = []
    if not package_dir.is_dir():
        errors.append("package path must be a directory")
        return PackageValidation(_deduplicate(errors), package_dir, None, None, None, None)

    plugin_root, manifest_path = select_plugin_root(package_dir, errors)
    if plugin_root is None or manifest_path is None:
        return PackageValidation(_deduplicate(errors), package_dir, plugin_root, manifest_path, None, None)
    if not _is_within(manifest_path, plugin_root):
        errors.append("selected manifest.json resolves outside the selected plugin root")
        return PackageValidation(_deduplicate(errors), package_dir, plugin_root, manifest_path, None, None)

    manifest: dict[str, Any] | None = None
    try:
        decoded = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(decoded, dict):
            errors.append("manifest JSON must contain an object")
        else:
            manifest = decoded
    except Exception as exc:  # noqa: BLE001 - report malformed packages as validation failures
        errors.append(f"manifest JSON parse failed: {exc}")

    entry_source: str | None = None
    entry_path: str | None = None
    if manifest is not None:
        plugin_id = manifest.get("id")
        if not isinstance(plugin_id, str) or not SAFE_ID.fullmatch(plugin_id):
            errors.append("manifest id must be a lowercase dotted/kebab identifier")
        for key in ("name", "version"):
            if not isinstance(manifest.get(key), str) or not manifest[key].strip():
                errors.append(f"manifest {key} is required")

        contributes_value = manifest.get("contributes", {})
        if not isinstance(contributes_value, dict):
            errors.append("manifest contributes must be an object")
            contributes: dict[str, Any] = {}
        else:
            contributes = contributes_value

        input_value = contributes.get("inputActions", [])
        sidebar_value = contributes.get("sidebar", [])
        fragments_value = contributes.get("htmlFragments", [])
        if not isinstance(input_value, list):
            errors.append("contributes.inputActions must be an array")
            input_actions: list[Any] = []
        else:
            input_actions = input_value
        if not isinstance(sidebar_value, list):
            errors.append("contributes.sidebar must be an array")
            sidebar: list[Any] = []
        else:
            sidebar = sidebar_value
        if not isinstance(fragments_value, list):
            errors.append("contributes.htmlFragments must be an array")
            html_fragments: list[Any] = []
        else:
            html_fragments = fragments_value

        if require_input_action and not input_actions:
            errors.append("at least one contributes.inputActions item is required")
        if require_html_fragment and not html_fragments:
            errors.append("at least one contributes.htmlFragments item is required")

        scripts_value = manifest.get("scripts", {})
        if not isinstance(scripts_value, dict):
            errors.append("manifest scripts must be an object")
            scripts: dict[str, Any] = {}
        else:
            scripts = scripts_value
        has_entry = "entry" in manifest
        has_legacy_entry = "actions" in scripts

        if has_entry:
            entry_source = "entry"
            entry_path = _validate_resource_path(
                plugin_root,
                manifest.get("entry"),
                "entry",
                errors,
                require_file=True,
            )
        elif has_legacy_entry:
            entry_source = "scripts.actions"
            entry_path = _validate_resource_path(
                plugin_root,
                scripts.get("actions"),
                "scripts.actions",
                errors,
                require_file=True,
            )

        # The legacy alias is ignored for loading when root `entry` exists, but
        # still must be syntactically safe if an author leaves both declarations.
        if has_entry and has_legacy_entry:
            _validate_resource_path(
                plugin_root,
                scripts.get("actions"),
                "scripts.actions",
                errors,
                require_file=False,
            )

        if (input_actions or sidebar) and not (has_entry or has_legacy_entry):
            errors.append(
                "entry is required when inputActions or sidebar actions are declared "
                "(legacy scripts.actions remains a compatibility alias)"
            )

        if "cover" in manifest:
            _validate_resource_path(plugin_root, manifest.get("cover"), "cover", errors, require_file=True)

        for index, action in enumerate(input_actions):
            if not isinstance(action, dict):
                errors.append(f"contributes.inputActions[{index}] must be an object")
                continue
            if "icon" in action:
                _validate_resource_path(
                    plugin_root,
                    action.get("icon"),
                    f"contributes.inputActions[{index}].icon",
                    errors,
                    require_file=True,
                )

        for index, fragment in enumerate(html_fragments):
            if not isinstance(fragment, dict):
                errors.append(f"contributes.htmlFragments[{index}] must be an object")
                continue
            _validate_resource_path(
                plugin_root,
                fragment.get("src"),
                f"contributes.htmlFragments[{index}].src",
                errors,
                require_file=True,
            )

    safe_files = _validate_package_members(plugin_root, errors)
    if require_marker_text:
        found_marker = False
        for path in safe_files:
            try:
                if require_marker_text in path.read_text(encoding="utf-8", errors="replace"):
                    found_marker = True
                    break
            except OSError:
                continue
        if not found_marker:
            errors.append(f"marker text not found in package files: {require_marker_text}")

    return PackageValidation(
        _deduplicate(errors),
        package_dir,
        plugin_root,
        manifest_path,
        entry_source,
        entry_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Tavo plugin package structure.")
    parser.add_argument("package_dir")
    parser.add_argument("--require-input-action", action="store_true", help="Require at least one contributes.inputActions item.")
    parser.add_argument("--require-html-fragment", action="store_true", help="Require at least one contributes.htmlFragments item.")
    parser.add_argument("--require-marker-text", default="", help="Require this text in at least one selected plugin-root file.")
    args = parser.parse_args()

    result = validate_package(
        Path(args.package_dir),
        require_input_action=args.require_input_action,
        require_html_fragment=args.require_html_fragment,
        require_marker_text=args.require_marker_text,
    )
    if result.errors:
        for error in result.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("tpg_package_ok")
    print(f"package_dir={result.package_dir}")
    print(f"plugin_root={result.plugin_root}")
    print(f"manifest={result.manifest_path}")
    print(f"entry_source={result.entry_source or 'none'}")
    if result.entry_path is not None:
        print(f"entry={result.entry_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
