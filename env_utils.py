from pathlib import Path


def load_local_env(filename: str = ".env") -> None:
    env_path = Path(filename)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key:
            import os

            os.environ.setdefault(key, value)
