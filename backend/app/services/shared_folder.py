"""The shared folder that `files.save_to_folder` copies into, and the copy itself.

The folder is chosen by an admin in Settings (stored as non-secret metadata in the credential store,
name `files`) or set with SHARED_FOLDER_PATH. It is a path on the WorkFlowOS server; with Docker it
must be mounted into the api and worker containers.

Safety rules, enforced here so every caller gets them:
- only a file inside the run's own sandbox can be copied (never an arbitrary server path);
- the copy's name is reduced to a plain file name (no directories, no `..`, no reserved names);
- an existing file is never overwritten: a free name like `invoice (2).pdf` is chosen, and the new
  file is created exclusively so two runs cannot race for the same name;
- the result must still be inside the folder after resolving links.
"""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
from typing import Optional, Tuple

from app import config
from app.services.credential_store import SHARED_FOLDER as STORE_NAME

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_MAX_NAME = 180
_MAX_TRIES = 1000


class SharedFolderError(Exception):
    """Base error; `code` is the BLOCKED reason an executor reports."""

    code = "FAILED"


class NotConfigured(SharedFolderError):
    code = "NOT_CONFIGURED"


class FolderUnavailable(SharedFolderError):
    code = "INTEGRATION_UNAVAILABLE"


class UnsafeSource(SharedFolderError):
    code = "INVALID_PARAMETER"


def configured_folder() -> Tuple[Optional[str], Optional[str]]:
    """(folder, source) where source is 'settings' or 'environment'; (None, None) when unset."""
    try:
        from app.services.credential_store import get_credential_store

        info = get_credential_store().info(STORE_NAME)
    except Exception:
        info = None
    if info and info.metadata.get("folder"):
        return str(info.metadata["folder"]), "settings"
    env = (os.getenv("SHARED_FOLDER_PATH") or "").strip()
    return (env, "environment") if env else (None, None)


def _protected_dirs() -> Tuple[Path, ...]:
    """Folders the shared folder may not be (or be inside): WorkFlowOS's own data and sandboxes."""
    # The key file lives next to the SQLite database by default, so its folder is the data folder.
    return (Path(config.secret_key_path()).resolve().parent, Path(config.SANDBOX_DIR).resolve())


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def check_folder(folder: str) -> Path:
    """Validate a folder for use (absolute, existing, writable, not WorkFlowOS's own data)."""
    raw = (folder or "").strip()
    if not raw:
        raise NotConfigured("Choose the shared folder in Settings > Integrations.")
    path = Path(raw)
    if not path.is_absolute():
        raise FolderUnavailable("Use the folder's full path (for example D:\\Shared\\Invoices or /mnt/shared/invoices).")
    resolved = path.resolve()
    if not resolved.is_dir():
        raise FolderUnavailable(f"The folder {raw} does not exist on the WorkFlowOS server.")
    for protected in _protected_dirs():
        if _inside(resolved, protected) or _inside(protected, resolved):
            raise FolderUnavailable("Choose a folder outside WorkFlowOS's own data and sandbox folders.")
    if not os.access(resolved, os.W_OK | os.X_OK):
        raise FolderUnavailable(f"WorkFlowOS cannot write to {raw}.")
    return resolved


def folder_status() -> Tuple[bool, str]:
    folder, _ = configured_folder()
    if not folder:
        return False, "No shared folder chosen"
    try:
        check_folder(folder)
    except SharedFolderError as e:
        return False, str(e)
    return True, "Shared folder ready"


def safe_file_name(name: str, fallback: str = "file") -> str:
    """A plain file name: no directories, unsafe characters, trailing dots/spaces or reserved names."""
    base = os.path.basename(str(name or "").replace("\\", "/"))
    base = _UNSAFE_CHARS.sub("_", base).strip().rstrip(". ")
    while base.startswith("."):
        base = base[1:]
    if not base:
        base = fallback
    stem, ext = os.path.splitext(base)
    if stem.upper() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    if len(stem) + len(ext) > _MAX_NAME:
        stem = stem[: max(1, _MAX_NAME - len(ext))]
    return f"{stem}{ext}"


@dataclass
class SavedFile:
    path: str
    file_name: str
    size_bytes: int
    sha256: str
    renamed: bool  # True when the requested name was taken and a free one was chosen


def resolve_source(source_file: str, sandbox_root: str) -> Path:
    """The run's own file: must exist inside its sandbox."""
    if not source_file or not str(source_file).strip():
        raise UnsafeSource("No downloaded file to save (download the attachment first).")
    sandbox = Path(sandbox_root).resolve()
    source = Path(str(source_file)).resolve()
    if not _inside(source, sandbox):
        raise UnsafeSource("Only a file downloaded by this run can be saved to the shared folder.")
    if not source.is_file():
        raise UnsafeSource("The downloaded file is missing from the run's sandbox.")
    return source


def plan_name(folder: Path, wanted: str) -> Tuple[str, bool]:
    """The name the copy would get now (for dry runs): wanted, or 'name (2).ext' if taken."""
    stem, ext = os.path.splitext(wanted)
    for i in range(1, _MAX_TRIES + 1):
        candidate = wanted if i == 1 else f"{stem} ({i}){ext}"
        if not (folder / candidate).exists():
            return candidate, i > 1
    raise FolderUnavailable(f"Too many files named like {wanted} in the shared folder.")


def copy_into(folder: Path, source: Path, wanted: str) -> SavedFile:
    """Copy `source` into `folder` under a free name; never overwrites; created exclusively."""
    stem, ext = os.path.splitext(wanted)
    data = source.read_bytes()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    for i in range(1, _MAX_TRIES + 1):
        candidate = wanted if i == 1 else f"{stem} ({i}){ext}"
        target = folder / candidate
        try:
            fd = os.open(target, flags, 0o644)
        except FileExistsError:
            continue
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        except BaseException:
            try:
                os.remove(target)
            except OSError:
                pass
            raise
        if not _inside(target.resolve(), folder):  # a link planted under that name
            os.remove(target)
            raise FolderUnavailable("The shared folder redirected the file outside itself; nothing was saved.")
        return SavedFile(
            path=str(target),
            file_name=candidate,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            renamed=i > 1,
        )
    raise FolderUnavailable(f"Too many files named like {wanted} in the shared folder.")


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()
