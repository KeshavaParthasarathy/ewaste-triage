"""Resolve immutable bundle resources separately from local app data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


APP_NAME = "E-Waste Triage"


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

        data_dir = Path.home() / "Library" / "Application Support" / APP_NAME
        return cls(
            resources_dir=resources_dir,
            static_dir=resources_dir / "server" / "static",
            model_bundle_dir=resources_dir / "models" / "production",
            reference_dir=resources_dir / "reference",
            data_dir=data_dir,
            history_database_path=data_dir / "history.sqlite",
            history_media_dir=data_dir / "media",
        )
