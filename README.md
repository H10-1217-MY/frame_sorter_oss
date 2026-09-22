# Frame Sorter

動画から一定間隔でフレームを取り出し、キーボード操作で学習用フォルダへ高速に振り分ける軽量ツールです。

## MVP 機能

- 動画ファイルを読み込み
- `N` フレームごとに表示
- `1 / 2 / 3` キーで `OK / NG / Unknown` に分類
- `S` でスキップ
- `Backspace` で直前の操作を Undo
- ROI を数値指定して画面に表示
- ROI のみを保存するモード
- 4K 動画を想定し、GUI には縮小画像を表示
- 動画デコードと保存処理は GUI スレッドから分離
- Python 実装を標準動作にし、C++ 高速化は任意

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -U pip
pip install -e .
frame-sorter
```

または:

```bash
python -m frame_sorter.main
```

## C++ 高速化を有効にする

C++ 部分は必須ではありません。ビルドしなくても Python / NumPy fallback で動作します。

### Linux

```bash
pip install -e ".[native]"
cmake -S native -B build/native \
  -Dpybind11_DIR="$(python -m pybind11 --cmakedir)"
cmake --build build/native -j
```

### Windows PowerShell

```powershell
pip install -e ".[native]"
cmake -S native -B build/native `
  -Dpybind11_DIR="$(python -m pybind11 --cmakedir)"
cmake --build build/native --config Release
```

ビルドに成功すると `frame_sorter/native_ext/` に `fast_core` が生成され、
次回起動時から自動的に利用されます。

現時点では C++ 側に `mean_abs_diff()` のサンプル実装を置いています。
今後、類似フレーム判定などのボトルネックをここへ移す想定です。

## キー操作

| Key | Action |
|---|---|
| `1` | OK |
| `2` | NG |
| `3` | Unknown |
| `S` | Skip |
| `Backspace` | Undo last action |
| `Space` | Next frame without saving |

## 出力例

```text
output/
├── OK/
│   └── sample_f000000120.jpg
├── NG/
├── Unknown/
└── session.jsonl
```

## 設計方針

- 4K フレームを大量に RAM に保持しない
- GUI 用表示は縮小する
- 元画像は必要なときだけ保存する
- C++ は「必須依存」ではなく optional acceleration にする
- まず計測してから、本当に遅い箇所だけネイティブ化する

## v0.1.1

- Fixed Backspace Undo when ROI / interval spin boxes have focus.
- Space is also handled as a window-level shortcut.

## v0.1.2

- Added a bottom progress bar showing the current position in the video.
- Displays current frame / total frames / percentage.
- The progress bar is read-only for now to avoid accidental seeking during annotation.

## v0.2.0

固定の `OK / NG / Unknown` を廃止し、任意の分類をGUIから追加できるようにしました。

- 右側の `＋ 分類を追加` から表示名・保存フォルダ名・キーを設定
- 対応する保存フォルダを自動作成
- `annotation_config.json` に設定保存
- 同じプロジェクトフォルダを開くと設定を復元
- 分類の編集・削除に対応
- 分類を削除しても保存済み画像フォルダは削除しない安全設計
- `Space` は次フレーム、`Backspace` はUndoとして予約

設定例:

```json
{
  "version": 1,
  "labels": [
    {"name": "写っている", "folder": "visible", "key": "1"},
    {"name": "写っていない", "folder": "not_visible", "key": "2"},
    {"name": "微妙", "folder": "unclear", "key": "3"}
  ]
}
```
