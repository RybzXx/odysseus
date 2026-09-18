"""Copy missing data without replacing conflicts. Record hashes for selective rollback."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


def publish_copy(temporary, target):
    """Publish without replacing an existing file or creating PRoot hard links."""
    if os.name == "nt":
        os.rename(temporary, target)
        return
    library = ctypes.CDLL(None, use_errno=True)
    rename = library.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    # AT_FDCWD and RENAME_NOREPLACE preserve atomic, exclusive publication.
    if rename(-100, os.fsencode(temporary), -100, os.fsencode(target), 1):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(target))


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_manifest(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def confined(root, relative):
    path = root / relative
    if not path.resolve().is_relative_to(root) or path.is_symlink():
        raise ValueError("Data path escapes its root or is a symbolic link")
    return path


def reconcile(source, destination, manifest, *, apply=False):
    """Refuse conflicts before copying. Originals and existing destinations remain intact."""
    source, destination = Path(source).resolve(strict=True), Path(destination).resolve()
    if source == destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError("Source and destination must be separate trees")
    manifest = Path(manifest).resolve()
    if apply and manifest.exists():
        raise ValueError("Use a new manifest path for each application")
    report = {"source": str(source), "destination": str(destination), "missing": [], "existing": 0, "conflicts": [], "created": []}
    for original in sorted(source.rglob("*")):
        if original.is_symlink():
            raise ValueError("Source contains a symbolic link")
        if not original.is_file():
            continue
        relative = original.relative_to(source).as_posix()
        target = confined(destination, relative)
        if original.suffix == ".json":
            json.loads(original.read_text(encoding="utf-8"))
        entry = {"path": relative, "sha256": digest(original), "bytes": original.stat().st_size}
        if target.exists():
            if target.is_file() and digest(target) == entry["sha256"]:
                report["existing"] += 1
            else:
                report["conflicts"].append(relative)
        else:
            report["missing"].append(entry)
    if not apply:
        return report
    if report["conflicts"]:
        raise ValueError("Destination conflicts must be resolved before copying")
    save_manifest(manifest, report)
    try:
        for entry in report["missing"]:
            original = confined(source, entry["path"])
            if digest(original) != entry["sha256"]:
                raise ValueError("Source changed after inventory")
            target = confined(destination, entry["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".migration-")
            os.close(fd)
            try:
                shutil.copyfile(original, temporary)
                if digest(Path(temporary)) != entry["sha256"]:
                    raise ValueError("Copy hash mismatch")
                with open(temporary, "r+b") as stream:
                    os.fsync(stream.fileno())
                publish_copy(temporary, target)
                report["created"].append(entry)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    finally:
        save_manifest(manifest, report)
    return report


def rollback(manifest):
    """Remove only copied files that still have the recorded hash. Keep later edits."""
    report = json.loads(Path(manifest).read_text(encoding="utf-8"))
    root = Path(report["destination"]).resolve(strict=True)
    removed, preserved = [], []
    for entry in report["created"]:
        path = confined(root, entry["path"])
        if path.is_file() and digest(path) == entry["sha256"]:
            path.unlink()
            removed.append(entry["path"])
        elif path.exists():
            preserved.append(entry["path"])
    return {"removed": removed, "preserved": preserved}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source")
    parser.add_argument("--destination")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    if args.rollback:
        if not args.apply:
            parser.error("Rollback requires --apply")
        result = rollback(args.manifest)
    else:
        if not args.source or not args.destination:
            parser.error("Source and destination are required")
        result = reconcile(args.source, args.destination, args.manifest, apply=args.apply)
    print(json.dumps({key: len(value) if isinstance(value, list) else value for key, value in result.items()}))
