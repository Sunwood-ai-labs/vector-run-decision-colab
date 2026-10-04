# Decision 2.0 × VECTOR RUN — Google Colab notebooks

Decision 2.0の7モデルを、既存の横スクロールゲーム **[VECTOR RUN](https://github.com/Sunwood-ai-labs/vector-run-benchmark)** で比較するColab実験リポジトリです。ゲーム本体・物理・観測API・録画機能はゲームのリポジトリで管理し、ここにはノートブック、モデル実行コード、計測結果、比較動画を置きます。

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Sunwood-ai-labs/vector-run-decision-colab/blob/main/notebooks/vector_run_decision_colab.ipynb)

## 現在の状態

6モデルを専用Colabで実測し、[結果表](docs/results.md)・[3×3比較動画](videos/vector-run-comparison.mp4)・[録画検証](videos/capture-qa.json)を公開しています。[公開結果](results/)にはゲーム記録、GPU実行記録、検証証拠を保存します。Sol-2B-Reasoningは配布元の固定revisionがHTTP 401を返したため、ゲーム未測定です。

3問系列は各モデル5シードすべてで衝突しました。ルール対照は全5シードで30秒の打切りまで走行しました。この小規模な設定での結果であり、モデルの一般的な決定能力の順位ではありません。64問系列は別表で示します。

過去の60Hz・4行動の別ゲームによる接続確認は成績から除外します。原本ハッシュを証明できなかった初回Kaiも[除外記録](results/excluded/README.md)として保存し、正式結果と動画には原本を加工せず再測定したKaiを使います。

## 実行構成

| リポジトリ | 管理するもの |
| --- | --- |
| [vector-run-benchmark](https://github.com/Sunwood-ai-labs/vector-run-benchmark) | ゲーム本体、120Hz物理、ジャンプ・リリース、観測と計測API、3×3再生・録画 |
| このリポジトリ | Colabノートブック、Decision 2.0読み込み、CLI運用、公開結果と動画 |

ゲームは固定commitで外部から取得します。ゲームのコードをコピーして二重管理しません。モデル重み、認証情報、Colabセッション識別子も公開物に含めません。

## Colabで比較する

Kai-0.6B、Eos-0.8B、Sol-2B、Sol-2B-Reasoning、Nox-4B、Lux-9B、Vega-27Bを対象にします。モデルごとに専用Git worktreeとColabランタイムを使い、Google Colab CLIで並列実行します。GPU枠の制限は記録し、空いた枠を再利用します。

ゲームの時間は推論中も進めます。行動は`wait / jump / release`、物理120Hz、判断機会は16tickごと。モデルには画面内の状態だけをJSONで渡し、コースの未来情報を渡しません。この観測方法は`structured-visible-state-v1`として、通常の画像入力と区別します。

主測定は3問・シード101/202/303/404/505。64問はシード101の別系列です。ゲームは終わりのない走者なので、30秒の上限に到達したランは打切りとして記録し、クリアとは扱いません。

GPU名、モデルrevision、BF16/FP32混在の読み込み条件、依存版、ゲームとノートブックのcommit、推論の実forward数、遅れて到着した回答も保存します。GPU条件が違う結果は同じ条件として順位付けしません。

ノートブックは[notebooks/vector_run_decision_colab.ipynb](notebooks/vector_run_decision_colab.ipynb)、Colab CLI手順は[experiments/colab](experiments/colab)にまとめます。正式測定はゲーム`717f02dc9852b88c253ace32f42fcb6d780ed0d3`と実行コード`b2e8fcbbf4b4f68931e4f9bbfbd434023348d3f0`を別々にcloneして固定します。後続の録画機能・文書・結果の追加で、この測定コードは変更しません。

## 3×3比較動画

7モデルとルール・無操作の2対照を9枠に配置します。同じシードの実測記録を同じ時計で等速再生し、ブラウザでキャプチャします。録画中に時間を止めたり、モデルごとに速度を変えたりしません。モデルを取得できず未測定の枠は、理由を静的に表示します。

個別Colabでの実測記録の再生であり、同期した9モデルの同時推論ではありません。元の入力ログとゲーム物理の照合、全フレームの動画デコード、代表画像の目視を検証に含めます。

動画は1920×1080・30fps・33秒です。共通シード101を1倍速で30秒再生し、終了した枠は結果を保持、最後の3秒も保持します。Sol-Reasoningの枠は「未測定: 配布元401」の静的表示です。ゲーム側の[録画手順](https://github.com/Sunwood-ai-labs/vector-run-benchmark/blob/main/docs/video-recording.md)から再作成できます。

## 出典

[固定モデルと配布元コードの監査](docs/model-sources.md)・[配布物とライセンス](NOTICE.md)。この小さなゲーム実験は、JevArenaやDecision Indexの再現ではありません。
