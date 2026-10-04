# 決断レーン

Decision 2.0 を測るための、自作の横スクロールゲームです。走者は文章を生成しません。1回の判断で、コースの状態に対する **action（4択）**、**commit（今動くか）**、**danger（0〜2）** を返します。問数を 64 にすると、同じ状態へプローブを足して「1回の往復で 64 問」を測れます。

モデルが無くても遊べます。ルール走者は、画面とプロンプトに書いてある閾値どおりに動く上限です。停止走者は何もしない下限です。

## 遊び方

`play.bat` を起動して、ブラウザで http://127.0.0.1:8734/ を開きます。ファイルを直接開くとモジュールが読めません。

| キー | 動作 |
| --- | --- |
| Space / ↑ / W | ジャンプ（箱と欠線） |
| ↓ / S | スライディング（梁） |
| J / K | ストライク（ドローン） |
| P | 一時停止 |
| R | 同じシードでもう一度 |

最初はルール走者が走っています。キーを押すとそのシードを自分で走り直せます。黄緑の縦線は、いちばん近い障害に対する作動距離です。

## ベンチ

画面の **12シードを測る** は、ルールと停止を必ず測ります。`serve-decision.bat` が http://127.0.0.1:8780 で応答していれば、モデル列も足します。

ヘッドレスでも同じ集計が出ます。

```powershell
node bench.mjs --seeds 12
node bench.mjs --agent remote --questions 64 --url http://127.0.0.1:8780/v1/systemone
```

見る数字:

- **クリア / 距離 / 被弾** — コースを最後まで走れたか
- **行動一致** — 書いたルールと同じ行動を選んだか
- **commit / 危険MAE** — 残りの2問がルールと合うか
- **一貫性** — 「commit が true」と「action が hold 以外」が矛盾していないか
- **p95** — 判断1回のミリ秒。ゲームは 8 フレーム（約 133ms）ごとに1回しか聞きません
- **プローブ** — 64問モードだけ。状態に埋め込んだ真偽を読めているか

判断まで止めるモードは品質向けです。走ったままのモードは、133ms に間に合うかを見ます。公開カードの中央値は Kai 4.9ms から Vega 71.4ms ですが、あれは公開元の GPU です。

## Decision 2.0 を繋ぐ

モック（ルールそのもの。重みは要りません）:

```powershell
py -3 server\decision_server.py --mock --port 8780
```

公開モデル。`transformers>=5.17` と、読み込む大きさに足る GPU かメモリが要ります。Vega-27B はアダプタなので `peft` も要ります。

```powershell
py -3 server\decision_server.py --model vllm-sr/Decision-2.0-Kai-0.6B --port 8780
```

エンドポイントは `POST /v1/systemone` です。`state` と `questions` を渡すと、`answers.action.choice` と各選択肢の `probabilities` が返ります。

## テスト

```powershell
node --test tests/engine.test.mjs
py -3 server\decision_server.py --self-test
```

ルール走者はシード 1〜24 を被弾ゼロでクリアします。モックサーバは同じ閾値で答えます。
