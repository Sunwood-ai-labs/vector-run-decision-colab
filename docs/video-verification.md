# 3×3 実測trace動画の再現・検証

`comparison.html` は VECTOR RUN の既存 `js/engine.js` / `js/render.js` を利用する1920×1080の9タイルプレイヤーです。Kai / Eos / Sol / Sol-Reasoning / Nox / Lux / Vega / rule / idle の順に配置します。README、既存index、mainは変更しません。

## 比較条件

- seed 1 / 3問 / 60物理frame毎秒 / 1× / 単一の `performance.now()` 共通時計。
- GPU推論は別のColab実測時に実行しています。画面は「実測trace再生 / Colab GPU」「同時モデル推論ではありません」と明記します。
- 各ゲームの終了frameでworldと結果を保持します。共通時計は終了後も進み、15秒で再生を終了します。
- 未着、失敗、容量不足のモデルは静的な未測定表示とします。ruleやmockでモデルを代用しません。
- `timestampMs` は共通の物理時計、`wallTimeMs` は元の測定時計です。録画で推論を再実行しません。

## 必要schema

ハーネスの `schemaVersion: 1` を使用します。

- `game: {name: 'VECTOR RUN', commit}`、`model: {id, revision, baseRevision}`、`hardware: {gpu, dtype, quantization, dependencies}`、`timing: 'realtime'`、`fps: 60`、`elapsedWallMs`。
- `episodes[]` の seed=1 / questions=3 を選択します。`initialWorld` は `createWorld` 互換の完全なworldです。
- `frames[]` は連続した1始まりのstep後frame。`action` を直前の `step` に1回だけ適用します。`timestampMs=frame*1000/60`、`wallTimeMs` は実測値。
- `state` は `{frame, player, done, cleared, failed, lastAction, lastHit, hazards, chips}`。hazards/chipsは全配列で動的値も含みます。
- `decisions[]` の成功statusは `applied` / `completed`、失敗は `error`、終端未完了は `cancelled_at_end`。`applicationFrame` はstep前の0始まりであり、frame.frameと混同しません。
- `result` / `frameCount` / `decisionCount` / `skippedOpportunities` を保持します。

プレイヤーは全frameを既存engineで事前再生し、記録されたstate全フィールドと一致することを確認します。欠落frame、seed違い、model ID違い、物理時計違い、state不一致は再生しません。64問の結果を3問の比較へ混在させません。

## 起動と録画

```powershell
node scripts/capture-server.mjs --port 8787
```

未着確認画面は `http://127.0.0.1:8787/comparison.html?capture=1`。既定 `capture/manifest.json` は全モデル未測定です。実測JSON到着後にmanifestを生成します。

```powershell
node scripts/capture-prepare.mjs --results results --output capture/manifest.measured.json
```

T3共同ブラウザで最初に `preview_status`、必要なら `preview_open` を使い、`preview_resize({mode:'freeform',width:1920,height:1080})`、`preview_navigate` で `http://127.0.0.1:8787/comparison.html?capture=1&manifest=capture/manifest.measured.json` を開きます。`preview_snapshot` で表示を確認します。明示的なunsupportedエラーがある場合のみ代替ブラウザを使用します。

`preview_evaluate` で `await window.capturePlayer.ready` を確認後、`preview_recording_start`、`window.capturePlayer.start()` の順に実行します。約15秒実時間待ち、`window.capturePlayer.status()` の `complete` / `elapsedMs` / tilesを保存後に `preview_recording_stop`。録画開始・終了の余白は速度変更せず残します。`capturePlayer` に時計停止や速度変更APIはありません。

取得した録画ファイルを次のように処理します。capture-logは再生前後のstatus、実際の録画時刻、manifestとsourceのハッシュを保存します。公開ログにsession IDや認証情報を入れません。

```powershell
node scripts/capture-qa.mjs --input RECORDING_PATH --output videos/vector-run-3x3.mp4 --manifest capture/manifest.measured.json --capture-log videos/capture-log.json
```

H.264 / CRF22 / yuv420p / faststartで圧縮し、元のtimestampを維持します。`ffprobe -count_frames`、1920×1080以上、duration維持、全frame decodeを検査します。開始・中央・終了の代表PNG3枚と `.qa.json` を `videos/` に保存します。既存成果物は上書きせず、別名で再実行します。

## 完了条件と現在の状態

GPU実測traceは未到着です。現在のmanifestは全9枠未測定であり、実測動画MP4はまだ生成していません。公開用MP4・PNG・QAは実測trace到着後に生成します。

完了には、source traceとengine stateの一致、実ブラウザの1×共通時計、ffprobe、全decode、代表frameで9モデル名と注意表示の可読性、終了tile保持のVisual QAが必要です。media QAはGPU推論の正当性を証明しないため、Colab担当の計測・モデルrevision・hardware記録と併せて確認してください。
