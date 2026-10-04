# Colab 実GPU runner

このrepositoryはNotebook、7モデルの監査済みmanifest、共通loaderとbatch runnerを管理します。ゲーム実装は外部の[vector-run-benchmark](https://github.com/Sunwood-ai-labs/vector-run-benchmark)が所有し、ゲームsourceをこのrepositoryへコピーしません。

## 現在の測定gate

[`handoffs/canonical-game.json`](../../handoffs/canonical-game.json) は明示的な `ready_for_measurement` status、`game.measurementCommit`（またはroot `measurementCommit`）、確定wireContract、pass済trace validatorをすべて満たす必要があります。`sourceCommit` はmeasurement pinではありません。runnerが読む機械可読条件は `wireContract.questionsPerCall` に `flagMeaning: simultaneous_questions_per_api_call` とq3/q64のquestion ID一覧、`resultDraft.validationStatus: passed` と `resultDraft.validator.{status: passed, command}`、`publicState.schema` です。Notebookはbenchmark checkout後、ゲームcheckout/GPU bootstrap前にrunner共通validatorを実行します。runnerもmodel load前に同じgateを通し、失敗時は `blocked` sidecarだけを出します。以前のprototype成果は正式測定0件として扱い、結果に再利用しません。

ゲーム担当がCLIレビュー後にready status、immutableなmeasurement SHA、正確なq3/q64 wire contract、trace schemaとpass済validatorをhandoffへ記録した後、親が統合commitを共有したら、Notebookの2つのSHA pinを更新します。`GAME_COMMIT` はcanonical gameのmeasurement SHA、`BENCHMARK_COMMIT` はこのColab repositoryのcommitです。双方とも40桁SHAで、checkoutのHEADと一致しなければrunnerは起動しません。

## モデルごとのColab実行

7モデル（Kai、Eos、Sol、Sol-Reasoning、Nox、Lux、Vega）は、各モデルに専用Colab runtimeと一意なColab CLI configを割り当て、同時に並列実行します。WSL側では `/home/makim/.local/bin/colab --auth adc` を使い、modelごとに別config/sessionを選びます。Notebookは他sessionを列挙・変更・停止せず、認証情報も受け取りません。

ゲーム側を別directoryへimmutable SHAでcheckoutし、CPU/GPU条件を確認してから、単一modelを実行します。CLIを直接使う場合:

```bash
uv run --no-project --no-managed-python --no-sync python experiments/colab/run_bench.py \
  --game-dir /content/vector-run-game \
  --game-commit GAME_MEASUREMENT_SHA \
  --benchmark-commit COLAB_BENCHMARK_SHA \
  --models single --model kai \
  --runtime-history /content/runtime-history-kai.json \
  --output-dir /content/vector-run-results/kai/RUN_ID
```

`--runtime-history` は担当者が今回の新VM/session evidenceから入力する必須JSONです。`runtimeReused`、`weightsCached`、`priorModelLoaded`、`priorSystemOneCall`、`priorInference`、`priorPrototypeGameRun` はそれぞれ `true` / `false` / `null`（unknown）を取り、各項目にevidence noteを付けます。旧VMの値を持ち越さず、モデル名だけから値を推定しません。Notebookの初期値はすべてunknownです。

runnerは外部checkoutの `scripts/decision-bench.mjs` を `cwd` として呼び、`--agent remote`、seeds `101,202,303,404,505` の3問系列、seed `101` の64問系列を分けて実行します。`--questions` は1回のSystem One API callにまとめる同時質問数で、dispatch回数ではありません。q3は `action` / `commit` / `danger` の3問、q64は同じ3問と61個の `noul` probeです。System One adapterはraw responseをそのまま返し、serverは `measurements` を追加します。responseのrequired answer fieldsを維持し、top-level `model` / `usage` / `measurements` やanswer `type` などの追加metadataも捨てません。各game CLI reportは `{model}-q3.game.json` / `{model}-q64.game.json` にbyte内容を変えず保存します。runner sidecarの `runnerStatus` はCLI processの終了状態だけを示し、game内status path/valueは別の `gameReportStatus` にrawで記録します。status値の意味分類は行いません。`aggregateMeasurementStatus` は常に `not_aggregated` で、CLI終了コードから測定成功を作りません。

ゲームは120Hz、16tickごとに判断、actionはwait/jump/releaseです。1 runの上限30秒・jump上限2はcensored条件で、clearやcollision完了として扱いません。runnerはgame reportを変換せずraw保存し、status名と出現箇所だけを別sidecarへ記録します。game statusから集計成功は導きません。

## 実GPU・モデル計測

bootstrapはPyTorch CUDA 13.0 wheelとNode `v24.15.0` を固定し、CUDA GPUがない場合はrunnerがCPU/mockへ切り替えずblocked JSONを出します。外部量子化とCPU offloadは行いません。モデル本体revision、PEFT base情報、loader metadata、forward hook、mixed BF16/FP32設定、loadMs、first/warm/steady API request、1秒request windowを保持します。first API requestはColab runtimeがcoldという意味ではありません。担当者入力のprior runtime history、HF pinned snapshotのload前後の存在/size、CUDA/Triton/torch extension cache directoryのload・系列前後snapshotも記録します。cache hit、download発生、kernel cache warmの正確な状態・秒数は観測できない場合 `unknown` とします。各game request/responseは推論完了後に保存し、ゲーム終了後に返るlate responseもdrainして記録します。

出力directoryはrepository外の新しいrun専用directoryにします。NotebookからJSON sidecarとgame reportをZIP downloadしてください。重み、認証情報、Colab session identifier、notebook outputsは保存しません。

## 3×3 movie

3×3 playerとcaptureはcanonical game repositoryの所有物です。このrepositoryにはprototype player/captureを残しません。handoffのtrace schemaとgame側rendererが確定した後、同じimmutable game checkout内のmovie CLIで各modelのraw q3 reportを読み込みます。動画はtrace playbackとして表示し、30秒censored runをclearとは表現しません。
