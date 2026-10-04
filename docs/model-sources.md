# Decision 2.0 モデル出典と loader 監査

監査日時: 2026-10-04 13:59 UTC。対象はユーザー指定の Kai / Eos / Sol / Sol-Reasoning / Nox / Lux / Vega の7モデル。Hugging Face の [vllm-sr organization API](https://huggingface.co/api/models?author=vllm-sr&search=Decision-2.0&full=true) で正式IDを確認し、全モデルが public・ungated であることを確認した。モデルrevisionは以下のcommitに固定する。実行用の機械可読情報は [model-manifest.json](../experiments/colab/model-manifest.json) にある。

## 固定された公開モデル

| 名前 | 公開カード（固定revision） | commit | manifestのloaded parameters | 入力上限/問 |
|---|---|---|---:|---:|
| Kai | [Decision-2.0-Kai-0.6B](https://huggingface.co/vllm-sr/Decision-2.0-Kai-0.6B/blob/cd49ea3813fd8ba0928a9a23ef6c9a0f2f0cd764/README.md) | `cd49ea3813fd8ba0928a9a23ef6c9a0f2f0cd764` | 597,103,104 | 8,192 |
| Eos | [Decision-2.0-Eos-0.8B](https://huggingface.co/vllm-sr/Decision-2.0-Eos-0.8B/blob/3594047d69f476f1d01cf84c593e213fc3a4dfe0/README.md) | `3594047d69f476f1d01cf84c593e213fc3a4dfe0` | 753,446,208 | 16,384 |
| Sol | [Decision-2.0-Sol-2B](https://huggingface.co/vllm-sr/Decision-2.0-Sol-2B/blob/64235bef55dad29387dd16da7c90e038bf2f0972/README.md) | `64235bef55dad29387dd16da7c90e038bf2f0972` | 1,883,930,944 | 16,384 |
| Sol-Reasoning | [Decision-2.0-Sol-2B-Reasoning](https://huggingface.co/vllm-sr/Decision-2.0-Sol-2B-Reasoning/blob/ace3ae7032a4f96ffe6be778b9a72e36b68d6e29/README.md) | `ace3ae7032a4f96ffe6be778b9a72e36b68d6e29` | 1,883,930,944 | 16,384 |
| Nox | [Decision-2.0-Nox-4B](https://huggingface.co/vllm-sr/Decision-2.0-Nox-4B/blob/25e8f67d1b486c647222df3aac640d2d5d736bbe/README.md) | `25e8f67d1b486c647222df3aac640d2d5d736bbe` | 4,208,383,488 | 16,384 |
| Lux | [Decision-2.0-Lux-9B](https://huggingface.co/vllm-sr/Decision-2.0-Lux-9B/blob/78bf3c03d9147aeb30b641edfe0e30ed04887ca5/README.md) | `78bf3c03d9147aeb30b641edfe0e30ed04887ca5` | 7,940,895,744 | 16,384 |
| Vega | [Decision-2.0-Vega-27B](https://huggingface.co/vllm-sr/Decision-2.0-Vega-27B/blob/7aec49ae11a18741706da549ab626b9052795fe7/README.md) | `7aec49ae11a18741706da549ab626b9052795fe7` | 29,365,153,792 | 32,768 |

Sol-Reasoning の正式repo名は `vllm-sr/Decision-2.0-Sol-2B-Reasoning`。公開カードはSolの継続学習モデルで同じ単一forward/APIと説明する。上表のparametersは公開manifestの値で、今回のGPU計測値ではない。カードの速度・精度も今回のVECTOR RUN実測に流用しない。

## remote loader と実API

7モデルの `config.json` は `AutoModel` → `modeling_decision2.Decision2Model` を指定する。同一の [remote loader](https://huggingface.co/vllm-sr/Decision-2.0-Kai-0.6B/blob/cd49ea3813fd8ba0928a9a23ef6c9a0f2f0cd764/modeling_decision2.py) がrevisionを固定してsnapshotを取得し、同梱runtime・packageファイルをmanifestのSHA-256で検証する。全モデルでloaderのSHA-256は `a3f700b3d2a5deb344821802248a5ea7ea06ccedc5af1823dca4e3e813c17fbb`。

```python
from transformers import AutoModel

model = AutoModel.from_pretrained(
    repo_id,
    revision=commit_sha,
    trust_remote_code=True,
    device_map={"": "cuda:0"},
    dtype="auto",
    bf16_resident=True,
)
result = model.system_one(state=state, questions=questions)
```

`dtype` / `torch_dtype` は `None` または `"auto"` のみ。`torch.bfloat16` を直接渡すと拒否される。GPUの演算はbackboneのBF16 autocastとFP32 headで、resident parametersはBF16で完全に表せるLinearをBF16、embeddings・norms・その他の値をFP32で保持する。CPUはFP32。`device_map="auto"` は単一device選択で、CPU offloadを提供しない。複数device、`quantization_config`、`max_memory`、`offload_folder` はこのremote loaderで非対応。`bf16_resident=False` はFP32コピーを保持するため、省メモリ設定ではない。

[runtime API](https://huggingface.co/vllm-sr/Decision-2.0-Kai-0.6B/blob/cd49ea3813fd8ba0928a9a23ef6c9a0f2f0cd764/decision2/api.py) と [request/answer処理](https://huggingface.co/vllm-sr/Decision-2.0-Kai-0.6B/blob/cd49ea3813fd8ba0928a9a23ef6c9a0f2f0cd764/decision2/_vendor/dev2model/infer.py) の入力仕様:

- `state`: JSON文字列・object・array。トップレベルの数値/bool/nullは不可。object内の値はJSONで表せる有限値。
- `questions`: 空でない `question_id -> question` mapping。各IDは空でない文字列。
- `choice`: `type="choice"`、`instructions`、`criteria={option_id: description}`。全選択肢を2〜255件渡す。
- `noul`: `type="noul"`、`instructions`。criteriaを省略するとfalse/trueを補う。
- `score`: `type="score"`、`instructions`、順序付きcriteria配列（2〜10段階）。

戻り値はJSON化可能なdictで `model`（package名）、`answers`（質問IDごとの回答）、`usage={input_tokens, output_tokens: 0}`。choice回答は `{type, choice: option_id, probabilities: {option_id: p}, confidence}`、noulは `{type, noul: P(true)}`、scoreは `{type, score: 0起点の期待値, probabilities, confidence, legend}`。`input_tokens` は各質問入力長の合計。choiceのconfidenceは正規化entropyであり、TypeSafeのconfidence式との数値一致を主張しない。

入力上限超過は切り捨てず `answers[id].error="max_length_exceeded"` を返す。不正質問は `invalid_question`、不正出力は `invalid_model_output`。HTTP 200やdict返却だけで成功扱いせず、必要な全回答と選択されたactionを検査する。質問数はbatchの行数となり、同じstateでも各質問が独立にencodeされる。`share_context` はデフォルト無効で、今回の同条件比較でも無効を維持する。

## Vega のPEFT baseとメモリ

[Vega manifest](https://huggingface.co/vllm-sr/Decision-2.0-Vega-27B/blob/7aec49ae11a18741706da549ab626b9052795fe7/MODEL_MANIFEST.json) と [adapter config](https://huggingface.co/vllm-sr/Decision-2.0-Vega-27B/blob/7aec49ae11a18741706da549ab626b9052795fe7/adapter/adapter_config.json) を確認した。`Qwen/Qwen3.8-27B@1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0` に未mergeのPEFT LoRA（rank512 / alpha1024 / PEFT0.21.0）とdecision headを載せる。baseの固定revisionもHF APIで存在・公開・ungatedを確認した。adapter configの `base_model_name_or_path` / `revision` はnullなので、それらを根拠にbaseを推測してはいけない。正しいbaseはpackage manifestからremote loaderが取得し、base全ファイルのSHA-256を照合する。

manifestの外部text baseは25,624,600,064 parameters、adapterは3,735,289,856、headは5,263,872。baseをすべてBF16と仮定する最小の算術見積もりで約47.73GiB、FP32 LoRAで約13.92GiB、FP32 headで約0.02GiB、合計約61.67GiB。この値は実測peak memoryではなく、FP32で残るbase parameters・activation・一時allocationを含まない。40GB GPUでは不足が見込まれ、80GB GPUでも実ロードを検証する必要がある。量子化/offloadを加えた別runtimeを実行する場合は公開runtimeとの変更を明記し、同一条件の非量子化結果と混同しない。

## 依存環境と検証の範囲

公開manifestのscored runtimeは Python3.12.13、Transformers5.17.0、safetensors0.8.0、tokenizers0.23.2。Kai以外のQwen3.5 hybridには causal-conv1d1.7.0、flash-linear-attention0.5.2、Triton3.7.1が記載される。Vegaは追加でPEFT0.21.0、huggingface_hub1.31.0。公開torchは `2.12.0+git6bbd260` のROCm7.2 buildで、ColabのNVIDIA/CUDA環境とは異なる。HIP graph / gfx942向けfused kernelsの実行条件も異なるため、カード記載の速度やparityをColabに保証しない。実行側はactual Python・torch・CUDA・driver・GPU・kernels・各依存versionを記録する。

今回の監査では、7repoそれぞれのrevision APIが固定SHAと一致することを確認し、取得した11小ファイル（公開カード・config・manifest対象remoteコード・runtime/vendorコードなど）を `files_sha256` に照合して全77ファイル一致。機械可読manifestに照合対象名と公開manifest自体のSHA-256を保存した。モデルweightsおよびVega base weightsのdownload/全byte検証・GPUロード・実forwardはこの出典監査の完了条件に含めず、実行結果に別記録する。
