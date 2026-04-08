from pathlib import Path


def process_email(source_path: Path, context: dict[str, str]) -> bool:
    """Placeholder spam detector that allows mail to continue unchanged."""
    # This subprocessor currently only decides whether processing should continue.
    _ = source_path
    _ = context
    return True
