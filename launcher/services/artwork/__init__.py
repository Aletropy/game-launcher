"""Artwork: storage, display cache and cleanup."""

from launcher.services.artwork.cleanup import (
    ArtFile,
    ArtworkCleaner,
    CleanupReport,
    CleanupResult,
)
from launcher.services.artwork.specs import (
    EXTENSIONS,
    GRID,
    HERO,
    ICON,
    LOGO,
    SPECS,
    ArtSpec,
    classify,
    encode,
    load_image,
    slug,
)
from launcher.services.artwork.store import ArtworkService

__all__ = [
    "EXTENSIONS",
    "GRID",
    "HERO",
    "ICON",
    "LOGO",
    "SPECS",
    "ArtFile",
    "ArtSpec",
    "ArtworkCleaner",
    "ArtworkService",
    "CleanupReport",
    "CleanupResult",
    "classify",
    "encode",
    "load_image",
    "slug",
]
