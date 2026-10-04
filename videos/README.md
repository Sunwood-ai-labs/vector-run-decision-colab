# 3×3比較動画

[動画](vector-run-comparison.mp4)は共通シード101の実測記録を1倍速で再生したものです。1920×1080、30fps、33秒。6モデルとルール・無操作の2対照を再生し、Sol-Reasoningは配布元401による未測定の静的表示です。推論中もゲームを進めた記録であり、9モデルの同時推論ではありません。

[capture-qa.json](capture-qa.json)にブラウザー時計、開始時刻の差、最大フレーム間隔、全990フレームのデコード、代表画像の目視結果を保存しています。[capture-inputs.json](capture-inputs.json)は入力の固定スナップショットで、そこから参照する元ファイルのSHAも検証済みです。[formal-results.json](formal-results.json)は録画機の絶対パスを含む元の一覧です。

別のclone先で再録する場合は、このリポジトリのルートから次のPythonを実行し、元の一覧を変更せずパスを付け替えた一覧を作ります。

```python
import json
from pathlib import Path, PureWindowsPath

root = Path.cwd().resolve()
original_root = PureWindowsPath("C:/Prj/decision-lane")
inventory = json.loads((root / "videos/formal-results.json").read_text(encoding="utf-8"))
def local_path(value):
    return str(root.joinpath(*PureWindowsPath(value).relative_to(original_root).parts))
for target in inventory["targets"].values():
    if "q3Paths" in target:
        target["q3Paths"] = [local_path(value) for value in target["q3Paths"]]
    if "evidence" in target:
        target["evidence"] = local_path(target["evidence"])
destination = root / "artifacts/replay/formal-results.json"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
```

ゲームのリポジトリもcloneし、[録画手順](https://github.com/Sunwood-ai-labs/vector-run-benchmark/blob/main/docs/video-recording.md)の`--formal-results`に上記の一覧を指定します。出力は`artifacts/replay/video`など別の場所へ保存してください。公開原本の`videos/`と`results/`は上書きしません。
