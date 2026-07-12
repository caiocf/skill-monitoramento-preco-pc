from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    venv_dir = root / ".venv"
    python = _venv_python(venv_dir)

    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], cwd=str(root), check=True)

    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], cwd=str(root), check=True)
    subprocess.run([str(python), "-m", "pip", "install", "-r", "requirements.txt"], cwd=str(root), check=True)
    subprocess.run([str(python), "-m", "playwright", "install", "chromium"], cwd=str(root), check=True)

    print("Instalacao concluida. Teste com:")
    print(f"{python} run.py \"Ryzen 9 9950X3D\" --json")
    return 0


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


if __name__ == "__main__":
    raise SystemExit(main())
