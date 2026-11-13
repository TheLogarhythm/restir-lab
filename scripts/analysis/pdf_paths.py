"""Portable source paths for generated PDF analysis and visual reports.

Repository inputs are saved relative to the repository root, independently of
where the checkout lives.  Inputs genuinely outside that root remain absolute
and are explicitly labeled; legacy untagged inputs keep their original
manifest-relative / absolute interpretation.
"""
from pathlib import Path, PurePosixPath, PureWindowsPath


ROOT = Path(__file__).resolve().parents[2]


def record_path(value, *, workspace=None):
    """Serialize a real source path without disguising an external input."""
    root=Path(ROOT if workspace is None else workspace).resolve(strict=True)
    source=Path(value).resolve(strict=True)
    if source.is_relative_to(root):
        return {'path':source.relative_to(root).as_posix(),'path_base':'repository_root'}
    return {'path':str(source),'path_base':'external_absolute'}


def resolve_record(value, *, workspace=None, legacy_base=None):
    """Resolve a tagged path or preserve the legacy input interpretation.

    Tagged repository paths cannot contain traversal, a drive, or a symlink
    escape. Legacy untagged paths keep the old manifest-relative or absolute
    semantics so saved manifests continue to work on their original host.
    """
    root=Path(ROOT if workspace is None else workspace).resolve(strict=True)
    if isinstance(value,dict):
        text=value.get('path')
        base=value.get('path_base')
    else:
        text=value
        base=None
    if not isinstance(text,(str,Path)) or not str(text):
        raise ValueError('Expected a nonempty PDF source path')
    text=str(text)
    path=Path(text)
    windows=PureWindowsPath(text)
    posix=PurePosixPath(text)
    if base=='repository_root':
        if (path.is_absolute() or windows.drive or windows.root or posix.is_absolute()
                or '\\' in text or '..' in windows.parts or '..' in posix.parts):
            raise ValueError('Repository path must be contained and relative')
        resolved=(root/path).resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise ValueError('Repository path escapes workspace')
        return resolved
    if base=='external_absolute':
        if not path.is_absolute():
            raise ValueError('External path must be absolute on this host')
        return path.resolve(strict=True)
    if base is not None:
        raise ValueError('Unknown PDF path base')
    if not path.is_absolute() and (windows.drive or windows.root or posix.is_absolute()):
        raise ValueError('Legacy absolute path cannot be resolved on this host')
    if path.is_absolute():
        return path.resolve(strict=True)
    return (Path(legacy_base if legacy_base is not None else root)/path).resolve(strict=True)
