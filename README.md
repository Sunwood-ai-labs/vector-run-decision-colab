# VECTOR RUN × Decision 2.0 × Google Colab

横スクロールゲームをDecision 2.0の7モデルで走らせ、クリア・被弾・行動・推論遅延を測る実験です。**推論中もゲームの時間を進めます。** モデルごとに専用Colabランタイムで実行し、7モデルと2つの対照走者を3×3の動画で比較します。

[![Code verification](https://github.com/Sunwood-ai-labs/vector-run-decision-colab/actions/workflows/verify.yml/badge.svg)](https://github.com/Sunwood-ai-labs/vector-run-decision-colab/actions/workflows/verify.yml)
[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Sunwood-ai-labs/vector-run-decision-colab/blob/main/notebooks/vector_run_decision_colab.ipynb)

## 比較条件

Kai-0.6B、Eos-0.8B、Sol-2B、Sol-2B-Reasoning、Nox-4B、Lux-9B、Vega-27Bを対象にします。重みはリポジトリに含めません。

同じ状態と`hold / jump / slide / strike`の4候補を渡します。主測定は`action / commit / danger`の3問、シード1・2・3。64問の測定はシード1の別系列です。ルール走者とholdのみの走者は、モデルとは別の対照です。

GPU、モデルrevision、dtype、量子化、依存版を記録します。GPUの同時起動枠に達した場合は制限を記録し、空いた枠を使います。詳しくは[計測方法](docs/benchmark-method.md)を参照してください。

## 遊ぶ

Windowsでは`play.bat`を起動して、<http://127.0.0.1:8734/>を開きます。Pythonとuvがある環境では次でも起動できます。

```sh
uv run --no-project --python 3.12 -m http.server 8734 --bind 127.0.0.1
```

| キー | 動作 |
| --- | --- |
| Space / ↑ / W | ジャンプ：箱、欠線 |
| ↓ / S | スライディング：梁 |
| J / K | ストライク：ドローン |
| R | 同じシードで再走 |

ルール走者はモデルの推論結果ではありません。モデルで遊ぶにはColabのノートブックまたは推論サーバーを使います。

## リアルタイムで測る

Node.js 24とPythonを使います。物理は60FPS、判断機会は8フレームごと。推論中も物理を進め、返ってきた行動を1回だけ適用します。反射ルールによる介入や候補削減は行いません。

```sh
node bench.mjs --agent rule --timing realtime --seeds 3 --questions 3 --trace --output results/rule-q3.json
node bench.mjs --agent idle --timing realtime --seeds 3 --questions 3 --trace --output results/idle-q3.json
node bench.mjs --agent remote --timing realtime --seeds 3 --questions 3 --trace --model vllm-sr/Decision-2.0-Kai-0.6B --url http://127.0.0.1:8780/v1/systemone --output results/kai-q3.json
```

64問は`--questions 64 --seeds 1`を指定し、別ファイルに保存します。

## 3×3動画

9枠は7モデル・ルール走者・hold走者です。共通シードを等速で再生し、終了した枠は結果を表示したまま全体の時計を進めます。

動画は**保存した実測traceの等速再生をブラウザでキャプチャしたもの**です。9モデルの同期した同時推論を撮影したものではありません。失敗や未測定の枠はその状態を表示し、ルール走者で置き換えません。

## コードの確認

```sh
node --test tests/*.test.mjs
uv run --no-project --python 3.12 server/decision_server.py --self-test
```

CIはゲームと接続コードを検証します。CIの成功だけでGPU推論やモデルのクリアを確認したとは扱いません。

このゲームは明示したルールへの追従とリアルタイム制御の小さな実験です。JevArenaやDecision Indexの再現ではありません。[ライセンス](LICENSE)・[モデルの出典](NOTICE.md)を参照してください。
