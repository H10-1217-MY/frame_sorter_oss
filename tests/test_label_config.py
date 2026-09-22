from pathlib import Path
from frame_sorter.label_config import LabelConfig, LabelDefinition


def test_label_config_roundtrip(tmp_path: Path):
    path = tmp_path / "annotation_config.json"
    config = LabelConfig(path)
    config.labels = [
        LabelDefinition(name="写っている", folder="visible", key="1"),
        LabelDefinition(name="微妙", folder="unclear", key="3"),
    ]
    config.save()
    loaded = LabelConfig(path)
    loaded.load()
    assert len(loaded.labels) == 2
    assert loaded.labels[0].folder == "visible"
    assert loaded.labels[1].key == "3"


def test_sanitize_folder_name():
    assert LabelConfig.sanitize_folder_name("a/b:c") == "a_b_c"
