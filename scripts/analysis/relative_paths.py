"""Store analysis file references relative to the document that owns them."""
import os
from pathlib import Path


def relative_to_document(path, directory):
    """Return a portable relative path from a document directory to a file.

    References may contain '..' because a report may reside below or beside
    its read-only inputs. Existing callers permit such external inputs. Windows
    cannot express cross-drive paths relatively, so that case is rejected.
    """
    path = Path(path).resolve()
    directory = Path(directory).resolve()
    try:
        return Path(os.path.relpath(path, directory)).as_posix()
    except ValueError as exc:
        raise ValueError('Analysis inputs and reports must be on the same volume') from exc


def rebase_record(record, source_directory, target_directory):
    """Copy a path/hash record to a target document's directory basis."""
    path = Path(record['path'])
    absolute = path if path.is_absolute() else Path(source_directory) / path
    return {**record, 'path': relative_to_document(absolute, target_directory)}
