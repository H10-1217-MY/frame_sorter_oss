from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


RESERVED_KEYS = {"SPACE", "BACKSPACE"}


@dataclass
class LabelDefinition:
    name: str
    folder: str
    key: str

    def normalized_key(self) -> str:
        return self.key.strip().upper()


class LabelConfig:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.labels: list[LabelDefinition] = []

    @staticmethod
    def sanitize_folder_name(name: str) -> str:
        name = name.strip()
        name = re.sub(r'[<>:"/\\|?*]+', "_", name)
        name = name.rstrip(". ")
        return name or "label"

    def load(self) -> None:
        if not self.path.exists():
            self.labels = []
            return

        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.labels = [
            LabelDefinition(
                name=item["name"],
                folder=item["folder"],
                key=item["key"],
            )
            for item in data.get("labels", [])
        ]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "labels": [asdict(label) for label in self.labels],
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
