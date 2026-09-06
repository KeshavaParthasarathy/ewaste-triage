"""Resolve immutable bundle resources separately from local app data."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys


APP_NAME = "E-Waste Triage"
_TEST_MODE_ENV = "EWASTE_TEST_MODE"
_TEST_SUPPORT_ENV = "EWASTE_TEST_APP_SUPPORT_DIR"


def test_mode_enabled() -> bool:
    """Return whether the explicit packaged-smoke mode is enabled."""
    return os.environ.get(_TEST_MODE_ENV) == "1"


def _test_support_dir() -> Path:
    value = os.environ.get(_TEST_SUPPORT_ENV)
    if not value:
        raise ValueError(f"{_TEST_SUPPORT_ENV} must be an absolute path in test mode")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{_TEST_SUPPORT_ENV} must be an absolute path in test mode")
    return path


@dataclass(frozen=True)
class AppPaths:
    """Filesystem locations owned or consumed by the desktop application."""

    resources_dir: Path
    static_dir: Path
    model_bundle_dir: Path
    reference_dir: Path
    data_dir: Path
    history_database_path: Path
    history_media_dir: Path

    @property
    def reference_database_path(self) -> Path:
        """Immutable compiled component-reference artifact bundled with the app."""
        return self.reference_dir / "components.sqlite"

    @property
    def release_manifest_path(self) -> Path:
        return self.resources_dir / "release" / "release-manifest.json"

    @property
    def build_metadata_path(self) -> Path:
        return self.resources_dir / "build-metadata.json"

    @classmethod
    def for_runtime(
        cls, frozen: bool, executable: Path | None = None
    ) -> "AppPaths":
        """Return paths for development or a PyInstaller-frozen application.

        ``executable`` is accepted so packagers and tests can state their runtime
        context explicitly. PyInstaller exposes extracted immutable resources via
        ``sys._MEIPASS``; neither it nor the executable directory is used for data.
        """
        del executable
        if frozen:
            try:
                resources_dir = Path(sys._MEIPASS)
            except AttributeError as exc:
                raise RuntimeError("frozen application resources are unavailable") from exc
        else:
            resources_dir = Path(__file__).resolve().parents[1]

        data_dir = (
            _test_support_dir()
            if test_mode_enabled()
            else Path.home() / "Library" / "Application Support" / APP_NAME
        )
        return cls(
            resources_dir=resources_dir,
            static_dir=resources_dir / "server" / "static",
            model_bundle_dir=resources_dir / "models" / "production",
            reference_dir=resources_dir / "reference",
            data_dir=data_dir,
            history_database_path=data_dir / "history.sqlite",
            history_media_dir=data_dir / "media",
        )
