from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    script = root / "scripts" / "pc_price_finder.py"
    if not script.exists():
        print(f"Script principal nao encontrado: {script}", file=sys.stderr)
        return 2

    python = _resolve_python(root)
    command = [str(python), str(script), *sys.argv[1:]]
    completed = subprocess.run(command, cwd=str(root))
    return completed.returncode


def _resolve_python(root: Path) -> Path:
    venv_python = _venv_python(root)
    if venv_python and venv_python.exists():
        return venv_python
    return Path(sys.executable)


def _venv_python(root: Path) -> Path | None:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


if __name__ == "__main__":
    raise SystemExit(main())
