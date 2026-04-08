from pathlib import Path
from typing import Optional


def process_email(source_path: Path, destination_dir: Path) -> Optional[Path]:
    """Claim a staged email, then pass it through unchanged for now."""
    destination_dir.mkdir(parents=True, exist_ok=True)

    # Claim the file first so no other worker processes the same message.
    locked_path = source_path.with_suffix(f"{source_path.suffix}.locked")
    try:
        source_path.rename(locked_path)
    except FileNotFoundError:
        return None

    # Write to a temp file in the destination so processed messages appear atomically.
    destination_path = destination_dir / source_path.name
    tmp_path = destination_dir / f"{source_path.name}.tmp"
    try:
        tmp_path.write_bytes(locked_path.read_bytes())
        tmp_path.rename(destination_path)
        # Remove the claimed source only after the processed copy is safely in place.
        locked_path.unlink()
        return destination_path
    except Exception:
        # Roll back partial output and release the claimed file for a later retry.
        if tmp_path.exists():
            tmp_path.unlink()
        try:
            locked_path.rename(source_path)
        except FileNotFoundError:
            pass
        raise
