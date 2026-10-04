# 配布物と出典

このリポジトリのノートブックとモデル計測コードはMITライセンスです。ゲーム本体とDecision 2.0のモデル重みは同梱しません。それぞれのライセンスと利用条件は配布元を確認してください。

- モデル配布元: [vLLM Semantic Router / Decision 2.0](https://huggingface.co/collections/vllm-sr/decision-20)
- APIの参照: [Kai-0.6Bモデルカード](https://huggingface.co/vllm-sr/Decision-2.0-Kai-0.6B)

ゲーム本体は [Sunwood-ai-labs/vector-run-benchmark](https://github.com/Sunwood-ai-labs/vector-run-benchmark) です。このリポジトリで別ゲームをVECTOR RUNへ改名した過去の試作は、正式なゲーム実装・測定結果から除外します。

本ベンチマークは画面内の構造化された状態を観測するゲーム制御と推論遅延を測ります。JevArenaやDecision Indexの再現ではありません。GPU、精度、観測方法、ゲーム条件の異なる結果は同じ性能として扱いません。
