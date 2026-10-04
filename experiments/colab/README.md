# VECTOR RUN の専用 Colab 実 GPU ベンチ

親が realtime harness を統合したゲーム一式を `/content/vector-run` に配置してから実行する。`bench.mjs` の `--timing realtime --output --trace --metadata` がそろっていない場合は runner が blocked を記録する。既存の Colab session の停止・変更は行わない。

```bash
cd /content/vector-run
bash experiments/colab/bootstrap.sh
uv run --no-project --no-managed-python --no-sync python experiments/colab/run_bench.py \
  --models kai --output-dir results/kai --game-commit GAME_COMMIT_SHA
```

`--models` は `kai eos sol sol-reasoning nox lux vega` のいずれかを指定できる。モデル別専用 VM を並列に使う場合も VM 内は単一モデルとし、GPU が違えば別条件として比較する。全モデルを同じ VM で逐次測定する場合のみ `--models` を省略する。GPU が大きくても外部量子化・CPU offload は audited remote loader が対応していない。

各モデルを一度ロードし、3 問 seeds 1, 2, 3 と 64 問 seed 1 を別ファイル `{slug}-q3.json` と `{slug}-q64.json` に保存する。ゲーム側の episodes/frames と HTTP latency を保持し、runtime に依存版本、CUDA/GPU、ロード時間、system_one API 全体時間、peak allocated/reserved memory、request ごとの計測値を加える。API 全体時間には入力準備と出力整形も含まれ、純粋な neural system_one_ms（トークナイズとラッパーを含む全API時間。純粋な神経forward時間は未測定null）は未計測の null とする。first は各系列の request 1、warm は request 2、steady は request 3 以降。64 問の first は既に 3 問を実行した同じモデル上の最初の 64 問 request であり、cold load の測定ではない。ゲーム中に別の warmup request は送らない。

Python は uv を使う。bootstrap は固定版本をインストールし、torch の NVIDIA CUDA 13.0 wheel を使用する。モデルカードの ROCm release torch とは異なるため、actual versions を結果に残す。causal-conv1d / flash-linear-attention はインストールされていれば記録するが自動追加はしない。これらの不足でモデルを実行できない場合も blocked として記録する。

OOM、ロード失敗、ゲーム CLI 失敗、timeout も JSON 成果物にする。mock/ルールへの切替機能はない。partial/failed traces を成功と扱わない。公開結果に VM session ID、ADC、トークン、認証ログを含めない。notebook は outputs を空に保つ。

WSL Colab CLI は各担当の専用 `--config /tmp/vector-run-MODEL-colab-session.json` を必ず使う。現在の CLI の `--help` と skill を更新確認し、その config の VM にのみ bootstrap / runner を実行・成果物を download する。download と public sanitize を確認した後、その専用 session だけ stop する。runner と notebook は session lifecycle を変更しない。
