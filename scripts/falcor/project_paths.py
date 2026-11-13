"""Portable workspace paths for generated Falcor scene plans.

Serialized paths are POSIX-style and relative to the workspace root.  Runtime
consumers resolve them only at the filesystem boundary, after checking that
neither traversal, a foreign absolute path, nor a symlink escapes that root.
"""
from pathlib import Path, PurePosixPath, PureWindowsPath


PLAN_PATH_FIELDS = frozenset({
    'path', 'source', 'descriptor', 'scene_file', 'asset_root', 'ies_path',
    'baked_hdr', 'bake_receipt', 'fallback_hdr',
})


def resolve_workspace_path(value, root, *, strict=False):
    """Resolve a workspace-relative or same-workspace legacy absolute path."""
    if not isinstance(value, (str, Path)) or not str(value):
        raise ValueError('Expected a nonempty workspace path')
    text=str(value)
    root=Path(root).resolve(strict=True)
    path=Path(text)
    windows=PureWindowsPath(text)
    posix=PurePosixPath(text)
    if not path.is_absolute() and (windows.drive or windows.root or posix.is_absolute()):
        raise ValueError('Foreign or drive-relative absolute path: '+text)
    if not path.is_absolute() and ('..' in windows.parts or '..' in posix.parts):
        raise ValueError('Workspace path traversal: '+text)
    candidate=(path if path.is_absolute() else root/path).resolve(strict=strict)
    if not candidate.is_relative_to(root):
        raise ValueError('Path escapes workspace: '+text)
    return candidate


def workspace_path(value, root, *, strict=False):
    """Return a portable, workspace-relative path, checking its location."""
    root=Path(root).resolve(strict=True)
    return resolve_workspace_path(value,root,strict=strict).relative_to(root).as_posix()


def remap_plan_paths(value, root, *, to_absolute):
    """Copy a scene plan, resolving or relativizing recognized path fields.

    Raw glTF URIs and scene-node paths use different coordinate systems and
    are intentionally not treated as workspace paths. Legacy absolute fields
    are accepted only when they already point inside the current workspace.
    """
    if isinstance(value,dict):
        result={}
        for key,item in value.items():
            if key in PLAN_PATH_FIELDS and isinstance(item,str):
                result[key]=(str(resolve_workspace_path(item,root)) if to_absolute
                             else workspace_path(item,root))
            else:
                result[key]=remap_plan_paths(item,root,to_absolute=to_absolute)
        return result
    if isinstance(value,list):
        return [remap_plan_paths(item,root,to_absolute=to_absolute) for item in value]
    return value
