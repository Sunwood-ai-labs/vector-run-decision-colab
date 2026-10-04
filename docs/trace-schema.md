# VECTOR RUN trace v1

COORDINATION.md の測定契約に対応する、ポリシー追従・実時間操作の記録。一般化能力のベンチマークとは呼ばない。モデルへの HTTP POST は `{model,state,questions}` のみで、gold は送らない。fake はテスト限定。

## CLI

```sh
node bench.mjs --agent remote --timing realtime --seeds 3 --questions 3 --url http://127.0.0.1:8780/v1/systemone --model MODEL --output FILE --trace --metadata METADATA.json
node bench.mjs --agent remote --timing realtime --seeds 1 --questions 64 --url http://127.0.0.1:8780/v1/systemone --model MODEL --output STRESS.json --trace --metadata METADATA.json
```

`--agent rule|idle` も同一時間設定・出力形式。`--seeds N` はシード 1..N、既定は 3 問なら 3、64 問なら 1。64 問はシード 1 の別測定。`--model` は remote 必須。`--timing` は realtime のみ。`--output` 省略時は JSON を標準出力、指定時はファイルへ保存して短い保存結果だけ表示。引数エラーは終了コード 1。接続・モデルエラーは記録して物理を続け、利用不可 JSON も保存する。`--trace` なしでは initialWorld/frames を省略するため動画用には必須。

`--metadata FILE` は `{model:{id,revision,baseRevision,baseRepo},hardware:{gpu,dtype,quantization,dependencies},gameCommit}`。未知値は null、無量子化を確認済みなら quantization に `"none"` を指定。dependencies はパッケージ名と実バージョンの object。モデル応答の `metadata` も同じ形で取り込み、ファイル値を優先。`--revision/--base-revision` はさらに優先。ゲームの commit/dirty は実行 checkout から自動採取し、転送 bundle の正確な識別には runner 指定の gameCommit を game.commit に優先反映する (checkoutCommit は実 checkout の値)。GPU/精度/revision は推測しない。

## JSON

トップレベル: `schemaVersion:1`, `benchmarkType:"policy_following"`, `status` (measured/partial/unavailable), `agent`, `model:{id,revision,baseRevision}`, `hardware:{gpu,dtype,quantization,dependencies}`, `game:{name:"VECTOR RUN",commit,dirty,policy}`, `timing:"realtime"`, `fps:60`, `decisionEvery:8`, `questions`, `seeds`, `elapsedWallMs`, `aggregate`, `episodes[]`。

各 episode: `seed`, `questions`, `timing`, `fps`, `status` (measured/partial/unavailable/no_response), `termination` (cleared/failed/engine_frame_limit), `elapsedWallMs`, `frameCount`, `decisionCount`, `skippedOpportunities`, `errorCount`, `cancelledCount`, `initialWorld`, `frames[]`, `decisions[]`, `finalState`, `result`。距離・被弾・クリア・得点・採点・latency の既存要約フィールドと `samples[]` も episode に置く。`result.frames/decisions` は最終フレーム数/要求数の数値、episode.frames/decisions は配列。`samples.gold` は記録後の採点用でモデル入力に含めない。

`initialWorld` は createWorld 互換の全物理状態 (seed/frame/level/player 等)。各 frame は `{frame,action,timestampMs,wallTimeMs,state}`:

- `frame` は step 後の world.frame、1 始まりで連続。action はその step に一度だけ与えた hold/jump/slide/strike。
- `timestampMs=frame*1000/60` はシード共通の 1x 物理時計。wallTimeMs はその step を実行した実測経過 ms。catchup では複数 frame の wallTimeMs が等しくなることがある。
- `state={frame,player,done,cleared,failed,lastAction,lastHit,hazards,chips}`。player は全物理フィールド、hazards/chips は完全配列 (x/spent/killed/taken 等含む)。省略差分形式ではない。finalState は同じ形。

各 decision: `id`, `dispatchFrame`, `dispatchMs`, `completionFrame`, `completionMs`, `applicationFrame`, `latencyMs`, `action`, `status`, `error`, `request:{state,questions}`, `response`。成功 response は解析済み action/probabilities/commit/danger/probe 情報と remote の `rawAnswers` (モデルが返した全回答・確率を保持)。dispatch/completion/applicationFrame は step 前の world.frame、0 始まり。applicationFrame=N の action は frames[N] (frame=N+1) に適用。

status は成功適用 `applied`、終端で応答済み未適用 `completed`、要求失敗 `error`、終端未応答 `cancelled_at_end` (pendingMs を追加)。未発生の completion/application/latency は null、error は正常時 null。`pending` は実行中のみ。latencyMs は HTTP を含む要求から応答までの実時間。未応答の推定 latency を捏造せず、latency 分布から除外する。

## 時計・採点・再生

物理は推論を待たず 60Hz、8 frame ごとに判断機会。未完了推論は一件のみ。busy/queued と wall-clock catchup 中に失われた判断機会は skippedOpportunities に計数する。返却 action は応答時までの物理 catchup 後、次の物理 frame で一度だけ適用する。推論終了までゲームを延長しない。自然終了時は未完了 HTTP を abort、既存 engine の最大 frame 制限を変更せず追加の打切りも設けない。

64 問は action/commit/danger と 61 個の入力ビット確認 probe。欠落・不正回答は期待問数の分母に残りミス。answerHits/answerTotal/answerAcc を全問に対して計算、probeAcc も期待 probe 数を分母とする。欠落 action は物理上 hold でも正解に数えず、commit は不正解、danger は最大誤差 2 として計数する。gold は dispatch 時状態の既存 ruleAction/dangerLevel と一致するポリシー追従指標である。

`replayEpisode(episode)` は initialWorld のコピーから各 frame.action を既存 step に一回ずつ与え、frameState と全 frame.state/finalState を厳密照合し不一致を拒否する。動画はこの検証済み物理時計を 1x 再生して drawWorld で描画する。モデル利用不可を baseline で置換しない。3x3 montage を同時 GPU 推論の証拠にしない。
