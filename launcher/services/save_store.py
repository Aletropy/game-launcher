"""The shared save store: adopting prefixes into it, and keeping them in.

One Windows user profile lives in Saves/ and every prefix holds symlinks
into it. A prefix can then be deleted and rebuilt without losing saves,
and a game finds its data whichever prefix it runs in.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from launcher.data.paths import Paths
from launcher.domain.save_layout import (
    CONFLICTS_DIR,
    LINKS,
    MANIFEST_FILE,
    LinkState,
    PathStatus,
    PrefixStatus,
    inspect_prefix,
    link_target,
    store_is_reachable,
)
from launcher.services.merge import (
    MergePlan,
    MergeResult,
    apply_merge,
    directory_size,
    plan_merge,
    prune_empty,
)


@dataclass
class PathPlan:
    """What adopting one shared path would do."""

    status: PathStatus
    #: None when the path needs no merge (missing, or already linked).
    merge: MergePlan | None = None
    skipped_reason: str = ""

    @property
    def label(self) -> str:
        return self.status.label

    @property
    def will_act(self) -> bool:
        return not self.skipped_reason and self.status.state.needs_work

    @property
    def action(self) -> str:
        if self.skipped_reason:
            return self.skipped_reason
        state = self.status.state
        if state is LinkState.LINKED:
            return "already shared"
        if state is LinkState.MISSING:
            return "create and link"
        if self.merge is None or self.merge.is_empty:
            return "link (nothing to move)"
        if not self.merge.moves and not self.merge.conflicts:
            # Every file is already in the store, byte for byte.
            return f"link ({len(self.merge.identical)} file(s) already shared)"
        parts = [f"move {len(self.merge.moves)} file(s)"]
        if self.merge.conflicts:
            parts.append(f"{len(self.merge.conflicts)} conflict(s)")
        if self.merge.identical:
            parts.append(f"{len(self.merge.identical)} already shared")
        return ", ".join(parts)


@dataclass
class AdoptPlan:
    """A dry run. Nothing has been touched."""

    prefix: Path
    status: PrefixStatus
    paths: list[PathPlan] = field(default_factory=list)
    blocked_reason: str = ""

    @property
    def can_run(self) -> bool:
        return not self.blocked_reason and any(p.will_act for p in self.paths)

    @property
    def total_moves(self) -> int:
        return sum(len(p.merge.moves) for p in self.paths if p.merge)

    @property
    def total_conflicts(self) -> int:
        return sum(len(p.merge.conflicts) for p in self.paths if p.merge)

    @property
    def total_bytes(self) -> int:
        return sum(p.merge.move_bytes for p in self.paths if p.merge)


@dataclass
class AdoptResult:
    """What adopting actually did."""

    linked: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    merges: list[tuple[str, MergeResult]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def conflict_count(self) -> int:
        return sum(len(m.conflicts) for _, m in self.merges)

    @property
    def moved_files(self) -> int:
        return sum(m.moved for _, m in self.merges)


@dataclass
class RepairResult:
    """What a pre-launch verification had to put right."""

    repaired: list[str] = field(default_factory=list)
    recovered_files: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def did_work(self) -> bool:
        return bool(self.repaired)


class SaveStore:
    """Owns Saves/ and the links into it."""

    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    # -- locations -----------------------------------------------------

    @property
    def root(self) -> Path:
        return self._paths.saves_dir

    @property
    def conflicts_root(self) -> Path:
        return self.root / CONFLICTS_DIR

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_FILE

    @property
    def exists(self) -> bool:
        return self.root.is_dir()

    @property
    def reachable(self) -> bool:
        """Whether games inside the Flatpak can follow links into it."""
        return store_is_reachable(self.root, self._paths.base)

    def size(self) -> int:
        return directory_size(self.root)

    def ensure(self) -> None:
        """Create the store skeleton."""
        for spec in LINKS:
            (self.root / spec.in_store).mkdir(parents=True, exist_ok=True)
        self.conflicts_root.mkdir(parents=True, exist_ok=True)

    # -- inspection ----------------------------------------------------

    def status(self, prefix: Path) -> PrefixStatus:
        return inspect_prefix(prefix, self.root, self._paths.base)

    def known_prefixes(self) -> list[Path]:
        """Every prefix the launcher manages, shared one first."""
        found = [self._paths.base / _shared_prefix_name(self._paths)]
        if self._paths.prefixes_dir.is_dir():
            found.extend(sorted(p for p in self._paths.prefixes_dir.iterdir() if p.is_dir()))
        return found

    def plan_adopt(self, prefix: Path) -> AdoptPlan:
        """Work out what adopting a prefix would do. Touches nothing."""
        status = self.status(prefix)
        plan = AdoptPlan(prefix=prefix, status=status)

        if not self.reachable:
            plan.blocked_reason = (
                "The store must live inside the launcher folder, or games "
                "running in the Steam Flatpak cannot follow the links."
            )
            return plan
        if not status.exists:
            plan.blocked_reason = "This prefix has not been created yet."
            return plan

        for path_status in status.paths:
            plan.paths.append(self._plan_path(path_status))
        return plan

    def _plan_path(self, status: PathStatus) -> PathPlan:
        if status.state is LinkState.FOREIGN_LINK:
            return PathPlan(
                status,
                skipped_reason=f"already links to {status.actual_target}",
            )
        if status.state is LinkState.NOT_A_DIR:
            return PathPlan(status, skipped_reason="a file is in the way")
        if status.state in (LinkState.LINKED, LinkState.MISSING):
            return PathPlan(status)
        return PathPlan(status, merge=plan_merge(status.path, status.target))

    # -- adopting ------------------------------------------------------

    def adopt(self, prefix: Path, *, prefer_newest: bool = True) -> AdoptResult:
        """Move a prefix's save data into the store and link it in."""
        result = AdoptResult()
        plan = self.plan_adopt(prefix)
        if plan.blocked_reason:
            result.errors.append(plan.blocked_reason)
            return result

        self.ensure()
        for path_plan in plan.paths:
            status = path_plan.status
            if path_plan.skipped_reason:
                result.skipped.append((status.label, path_plan.skipped_reason))
                continue
            if status.state is LinkState.LINKED:
                continue
            try:
                self._adopt_path(status, result, prefer_newest=prefer_newest)
            except OSError as e:
                result.errors.append(f"{status.label}: {e}")

        self._record(prefix, linked=True)
        return result

    def _adopt_path(
        self, status: PathStatus, result: AdoptResult, *, prefer_newest: bool
    ) -> None:
        status.target.mkdir(parents=True, exist_ok=True)

        if status.state is LinkState.REAL_DIR:
            merged = apply_merge(
                status.path,
                status.target,
                self.conflicts_root,
                prefer_newest=prefer_newest,
            )
            result.merges.append((status.label, merged))
            result.errors.extend(f"{status.label}: {e}" for e in merged.errors)

            prune_empty(status.path, keep_root=False)
            if status.path.exists():
                # Something could not be moved; leave it rather than
                # replacing a directory that still holds data.
                result.errors.append(
                    f"{status.label}: not empty after merging, left as it was"
                )
                return

        self._link(status)
        result.linked.append(status.label)

    def _link(self, status: PathStatus) -> None:
        """Point a prefix path at the store."""
        status.path.parent.mkdir(parents=True, exist_ok=True)
        if status.path.is_symlink() or status.path.exists():
            status.path.unlink()
        status.path.symlink_to(
            link_target(status.path, status.target, self._paths.base),
            target_is_directory=True,
        )

    # -- releasing -----------------------------------------------------

    def release(self, prefix: Path) -> AdoptResult:
        """Give a prefix its own copy again, so it stands alone.

        The store keeps its data; the prefix gets a full copy. Reversing
        an adopt is therefore expensive, but never lossy.
        """
        result = AdoptResult()
        status = self.status(prefix)
        if not status.exists:
            result.errors.append("This prefix has not been created yet.")
            return result

        for path_status in status.paths:
            if path_status.state is not LinkState.LINKED:
                continue
            try:
                path_status.path.unlink()
                shutil.copytree(
                    path_status.target,
                    path_status.path,
                    symlinks=True,
                    dirs_exist_ok=True,
                )
                result.linked.append(path_status.label)
            except OSError as e:
                result.errors.append(f"{path_status.label}: {e}")

        self._record(prefix, linked=False)
        return result

    # -- keeping links alive -------------------------------------------

    def verify(self, prefix: Path) -> list[PathStatus]:
        """Shared paths that are no longer linked as they should be."""
        status = self.status(prefix)
        if not status.exists:
            return []
        if status.unlinked:
            # Never adopted; nothing to repair.
            return []
        return [p for p in status.paths if p.state.needs_work]

    def repair(self, prefix: Path) -> RepairResult:
        """Restore links Proton replaced, keeping anything it wrote.

        wineboot recreates missing user folders on a Proton update and
        will replace a symlink with a real directory, quietly splitting
        saves in two. Anything written into the replacement is merged
        back into the store before the link is restored.
        """
        result = RepairResult()
        for status in self.verify(prefix):
            if status.state.is_blocked:
                result.errors.append(f"{status.label}: {status.describe}")
                continue
            try:
                if status.state is LinkState.REAL_DIR:
                    merged = apply_merge(
                        status.path, status.target, self.conflicts_root
                    )
                    result.recovered_files += merged.moved
                    result.errors.extend(
                        f"{status.label}: {e}" for e in merged.errors
                    )
                    prune_empty(status.path, keep_root=False)
                    if status.path.exists():
                        result.errors.append(
                            f"{status.label}: could not be emptied, left as it was"
                        )
                        continue
                status.target.mkdir(parents=True, exist_ok=True)
                self._link(status)
                result.repaired.append(status.label)
            except OSError as e:
                result.errors.append(f"{status.label}: {e}")
        return result

    # -- manifest ------------------------------------------------------

    def _read_manifest(self) -> dict:
        if not self.manifest_path.is_file():
            return {"prefixes": {}}
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"prefixes": {}}
        return data if isinstance(data, dict) else {"prefixes": {}}

    def _record(self, prefix: Path, *, linked: bool) -> None:
        """Note that a prefix joined or left the store."""
        data = self._read_manifest()
        entries = data.setdefault("prefixes", {})
        key = str(prefix)
        if linked:
            entries[key] = {"linked_at": datetime.now().isoformat(timespec="seconds")}
        else:
            entries.pop(key, None)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.manifest_path.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except OSError:
            # The manifest is a convenience; the links are the truth.
            pass

    def linked_prefixes(self) -> list[Path]:
        return [Path(p) for p in self._read_manifest().get("prefixes", {})]


def _shared_prefix_name(paths: Paths) -> str:
    """The shared prefix folder, honouring .prefix-name."""
    if paths.prefix_name_file.is_file():
        try:
            lines = paths.prefix_name_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return "Prefix"
        if lines and lines[0].strip():
            return lines[0].strip()
    return "Prefix"


def free_space(path: Path) -> int:
    """Bytes available on the filesystem holding a path."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return 0


def same_filesystem(a: Path, b: Path) -> bool:
    """Whether a move between two paths is a rename rather than a copy."""

    def device(path: Path) -> int | None:
        probe = path
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        try:
            return os.stat(probe).st_dev
        except OSError:
            return None

    da, db = device(a), device(b)
    return da is not None and da == db
