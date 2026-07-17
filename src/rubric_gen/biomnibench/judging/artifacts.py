"""Race-resistant judge output and directory identity access."""

from __future__ import annotations

import os
import secrets
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Iterator

from .models import JudgeRunConfig, JudgeTarget, safe_basename
from .scoring import JudgeScoreValidationError


@dataclass(frozen=True)
class OpenOutputDirectory:
    root_path: Path
    root_fd: int
    root_identity: tuple[int, int]
    path: Path
    fd: int


@dataclass(frozen=True)
class TargetDirectoryIdentities:
    run: tuple[int, int]
    workspace: tuple[int, int]
    output_root: tuple[int, int]
    canonical_run: str


class JudgeArtifactStore:
    """Own secure judge output I/O and bind target directory identities."""

    def __init__(self, config: JudgeRunConfig) -> None:
        self.config = config
        self._identity_lock = Lock()
        self._target_identities: dict[JudgeTarget, TargetDirectoryIdentities] = {}

    def output_dir(
        self,
        target: JudgeTarget,
        *,
        repeat_count: int,
        repeat_index: int = 1,
    ) -> Path:
        base = target.output_root / "judges" / self.config.review / target.task
        if repeat_count == 1:
            return self.safe_output_path(target.output_root, base)
        return self.safe_output_path(
            target.output_root,
            base / f"repeat-{repeat_index:02d}",
        )

    def safe_output_path(self, output_root: Path, candidate: Path) -> Path:
        root = output_root.expanduser().absolute()
        path = candidate.expanduser().absolute()
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise SystemExit(f"Judge output leaves output root: {candidate}") from exc
        current = root
        if current.is_symlink():
            raise SystemExit(f"Judge output root must not be a symlink: {current}")
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise SystemExit(f"Judge output path contains a symlink: {current}")
        try:
            if not path.resolve(strict=False).is_relative_to(root.resolve(strict=False)):
                raise SystemExit(f"Judge output leaves output root: {candidate}")
        except (OSError, RuntimeError) as exc:
            raise SystemExit(f"Invalid judge output path: {candidate}") from exc
        return path

    def snapshot_target_identities(
        self,
        target: JudgeTarget,
    ) -> TargetDirectoryIdentities:
        entries = (
            ("Target run directory", target.run_dir.expanduser().absolute()),
            ("Target workspace directory", target.workspace_dir.expanduser().absolute()),
            ("Target output root", target.output_root.expanduser().absolute()),
        )
        opened: list[tuple[str, Path, int]] = []
        try:
            for context, path in entries:
                opened.append((context, path, self.open_directory_fd(path, context)))
            for context, path, fd in opened:
                self.validate_directory_fd(fd, path, context)
            try:
                canonical_run = target.run_dir.expanduser().resolve(strict=True)
                canonical_run_stat = os.stat(canonical_run, follow_symlinks=False)
            except (OSError, RuntimeError) as exc:
                raise SystemExit(
                    f"Target run directory identity changed: {target.run_dir}"
                ) from exc
            run_identity = self.directory_fd_identity(opened[0][2])
            if (
                not stat.S_ISDIR(canonical_run_stat.st_mode)
                or (canonical_run_stat.st_dev, canonical_run_stat.st_ino)
                != run_identity
            ):
                raise SystemExit(
                    f"Target run directory identity changed: {target.run_dir}"
                )
            return TargetDirectoryIdentities(
                run=run_identity,
                workspace=self.directory_fd_identity(opened[1][2]),
                output_root=self.directory_fd_identity(opened[2][2]),
                canonical_run=str(canonical_run),
            )
        finally:
            for _, _, fd in reversed(opened):
                os.close(fd)

    def bind_target_identities(
        self,
        target: JudgeTarget,
        current: TargetDirectoryIdentities,
    ) -> None:
        with self._identity_lock:
            expected = self._target_identities.get(target)
            if expected is None:
                self._target_identities[target] = current
                return
        for label, path, expected_value, current_value in (
            ("run", target.run_dir, expected.run, current.run),
            ("workspace", target.workspace_dir, expected.workspace, current.workspace),
            (
                "output root",
                target.output_root,
                expected.output_root,
                current.output_root,
            ),
        ):
            if current_value != expected_value:
                raise SystemExit(f"Target {label} directory identity changed: {path}")
        if current.canonical_run != expected.canonical_run:
            raise SystemExit(f"Target run directory identity changed: {target.run_dir}")

    def target_identities(
        self,
        target: JudgeTarget,
    ) -> TargetDirectoryIdentities | None:
        with self._identity_lock:
            return self._target_identities.get(target)

    @staticmethod
    def directory_open_flags() -> int:
        return (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )

    @staticmethod
    def directory_fd_identity(fd: int) -> tuple[int, int]:
        value = os.fstat(fd)
        return value.st_dev, value.st_ino

    def validate_directory_fd(
        self,
        fd: int,
        path: Path,
        context: str,
        expected_identity: tuple[int, int] | None = None,
    ) -> None:
        try:
            fd_stat = os.fstat(fd)
            path_stat = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise SystemExit(f"{context} path identity changed: {path}") from exc
        if (
            not stat.S_ISDIR(fd_stat.st_mode)
            or not stat.S_ISDIR(path_stat.st_mode)
            or (fd_stat.st_dev, fd_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino)
            or (
                expected_identity is not None
                and (fd_stat.st_dev, fd_stat.st_ino) != expected_identity
            )
        ):
            raise SystemExit(f"{context} path identity changed: {path}")

    def open_directory_fd(self, path: Path, context: str) -> int:
        try:
            fd = os.open(path, self.directory_open_flags())
        except OSError as exc:
            raise SystemExit(
                f"{context} must be a stable regular directory: {path}"
            ) from exc
        try:
            self.validate_directory_fd(fd, path, context)
        except BaseException:
            os.close(fd)
            raise
        return fd

    @contextmanager
    def open_output_directory(
        self,
        output_root: Path,
        output_dir: Path,
        *,
        expected_root_identity: tuple[int, int],
        create: bool = True,
    ) -> Iterator[OpenOutputDirectory]:
        path = self.safe_output_path(output_root, output_dir)
        root = output_root.expanduser().absolute()
        relative = path.relative_to(root)
        root_fd = self.open_directory_fd(root, "Judge output root")
        current_fd: int | None = None
        current_path = root
        try:
            self.validate_directory_fd(
                root_fd, root, "Judge output root", expected_root_identity
            )
            current_fd = os.dup(root_fd)
            for part in relative.parts:
                if create:
                    try:
                        os.mkdir(part, mode=0o755, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                    except OSError as exc:
                        raise SystemExit(
                            "Could not create judge output directory component: "
                            f"{current_path / part}"
                        ) from exc
                try:
                    next_fd = os.open(
                        part, self.directory_open_flags(), dir_fd=current_fd
                    )
                except FileNotFoundError:
                    if not create:
                        raise
                    raise SystemExit(
                        f"Judge output directory component is unsafe: {current_path / part}"
                    )
                except OSError as exc:
                    raise SystemExit(
                        f"Judge output directory component is unsafe: {current_path / part}"
                    ) from exc
                os.close(current_fd)
                current_fd = next_fd
                current_path = current_path / part
                self.validate_directory_fd(
                    current_fd, current_path, "Judge output directory"
                )
            output = OpenOutputDirectory(
                root_path=root,
                root_fd=root_fd,
                root_identity=expected_root_identity,
                path=path,
                fd=current_fd,
            )
            self.safe_output_path(root, path)
            self.validate_output_directory(output)
            try:
                yield output
            finally:
                self.validate_output_directory(output)
        finally:
            if current_fd is not None:
                os.close(current_fd)
            os.close(root_fd)

    def validate_output_directory(self, output: OpenOutputDirectory) -> None:
        self.validate_directory_fd(
            output.root_fd,
            output.root_path,
            "Judge output root",
            output.root_identity,
        )
        self.validate_directory_fd(
            output.fd, output.path, "Judge output directory"
        )

    def read_output_bytes(self, output: OpenOutputDirectory, name: str) -> bytes:
        safe_basename(name, "judge output filename")
        self.validate_output_directory(output)
        file_fd: int | None = None
        try:
            file_fd = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=output.fd,
            )
            before = os.fstat(file_fd)
            named_before = os.stat(name, dir_fd=output.fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(before.st_mode)
                or not stat.S_ISREG(named_before.st_mode)
                or (before.st_dev, before.st_ino)
                != (named_before.st_dev, named_before.st_ino)
            ):
                raise JudgeScoreValidationError(
                    f"cached judge output is not a stable regular file: {name}"
                )
            chunks: list[bytes] = []
            while True:
                chunk = os.read(file_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(file_fd)
            named_after = os.stat(name, dir_fd=output.fd, follow_symlinks=False)
            if (
                self.stable_artifact_signature(before)
                != self.stable_artifact_signature(after)
                or not stat.S_ISREG(named_after.st_mode)
                or (after.st_dev, after.st_ino)
                != (named_after.st_dev, named_after.st_ino)
            ):
                raise JudgeScoreValidationError(
                    f"cached judge output changed while being read: {name}"
                )
            return b"".join(chunks)
        finally:
            if file_fd is not None:
                os.close(file_fd)
            self.validate_output_directory(output)

    def write_output_text(
        self, output: OpenOutputDirectory, name: str, text: str
    ) -> None:
        self.write_output_bytes(output, name, text.encode("utf-8"))

    def write_output_bytes(
        self, output: OpenOutputDirectory, name: str, payload: bytes
    ) -> None:
        safe_basename(name, "judge output filename")
        self.validate_output_directory(output)
        token = secrets.token_hex(12)
        temporary_name = f".{name}.{token}.tmp"
        backup_name = f".{name}.{token}.bak"
        temporary_exists = False
        backup_exists = False
        target_committed = False
        succeeded = False
        fd: int | None = None
        try:
            fd = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=output.fd,
            )
            temporary_exists = True
            remaining = memoryview(payload)
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0:
                    raise OSError("short write to judge output")
                remaining = remaining[written:]
            os.close(fd)
            fd = None
            self.validate_output_directory(output)
            try:
                os.replace(
                    name,
                    backup_name,
                    src_dir_fd=output.fd,
                    dst_dir_fd=output.fd,
                )
                backup_exists = True
            except FileNotFoundError:
                pass
            self.validate_output_directory(output)
            os.replace(
                temporary_name,
                name,
                src_dir_fd=output.fd,
                dst_dir_fd=output.fd,
            )
            temporary_exists = False
            target_committed = True
            self.validate_output_directory(output)
            if backup_exists:
                os.unlink(backup_name, dir_fd=output.fd)
                backup_exists = False
                self.validate_output_directory(output)
            succeeded = True
        except OSError as exc:
            raise SystemExit(
                f"Could not write judge output file: {output.path / name}"
            ) from exc
        finally:
            if fd is not None:
                os.close(fd)
            if not succeeded and target_committed:
                try:
                    os.unlink(name, dir_fd=output.fd)
                except (FileNotFoundError, OSError):
                    pass
            if not succeeded and backup_exists:
                try:
                    os.replace(
                        backup_name,
                        name,
                        src_dir_fd=output.fd,
                        dst_dir_fd=output.fd,
                    )
                    backup_exists = False
                except OSError:
                    pass
            if temporary_exists:
                try:
                    os.unlink(temporary_name, dir_fd=output.fd)
                except FileNotFoundError:
                    pass
            if backup_exists:
                try:
                    os.unlink(backup_name, dir_fd=output.fd)
                except FileNotFoundError:
                    pass

    def unlink_output_file(self, output: OpenOutputDirectory, name: str) -> None:
        safe_basename(name, "judge output filename")
        self.validate_output_directory(output)
        tombstone_name = f".{name}.{secrets.token_hex(12)}.stale"
        tombstone_exists = False
        succeeded = False
        try:
            os.replace(
                name,
                tombstone_name,
                src_dir_fd=output.fd,
                dst_dir_fd=output.fd,
            )
            tombstone_exists = True
        except FileNotFoundError:
            self.validate_output_directory(output)
            return
        except OSError as exc:
            raise SystemExit(
                f"Could not remove stale judge output: {output.path / name}"
            ) from exc
        try:
            self.validate_output_directory(output)
            os.unlink(tombstone_name, dir_fd=output.fd)
            tombstone_exists = False
            self.validate_output_directory(output)
            succeeded = True
        except OSError as exc:
            raise SystemExit(
                f"Could not remove stale judge output: {output.path / name}"
            ) from exc
        finally:
            if not succeeded and tombstone_exists:
                try:
                    os.replace(
                        tombstone_name,
                        name,
                        src_dir_fd=output.fd,
                        dst_dir_fd=output.fd,
                    )
                except OSError:
                    pass

    @staticmethod
    def stable_artifact_signature(value: os.stat_result) -> tuple[int, ...]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
