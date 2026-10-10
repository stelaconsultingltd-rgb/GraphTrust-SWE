"""Fingerprint the executable resource independently of Git availability."""
from pathlib import Path
import hashlib

from .io import digest


def implementation_sha256() -> str:
    root = Path(__file__).parent
    files = [{"path": path.relative_to(root).as_posix(),
              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
             for path in sorted(root.rglob("*.py")) if "__pycache__" not in path.parts]
    return digest(files)


def extractor_sha256() -> str:
    return hashlib.sha256((Path(__file__).parent / "graph.py").read_bytes()).hexdigest()
