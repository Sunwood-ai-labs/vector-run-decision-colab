# VECTOR RUN 正式ベンチマーク結果

game `717f02dc9852b88c253ace32f42fcb6d780ed0d3` / benchmark `b2e8fcbbf4b4f68931e4f9bbfbd434023348d3f0`。物理120 Hz、1x共通時計で推論中も物理を進めるrealtime計測です。

GPU機種が異なるため、system_one_msのモデル間速度順位は付けません。system_one_msはtokenization/wrapperを含むAPI同期時間で、純forward時間ではありません。q3の最初のAPI呼び出しと後続呼び出しを分け、q64は同一プロセスでq3後に実行した記録だけを示します。

各モデルの標本数は少数です。30秒打切りepisodeは生存時間・距離の下限値として扱い、打切りが1件でもある場合はclear率を表示しません。未測定は成績0や敗北を意味しません。late answerはゲームへ適用されなかった回答数です。

## q3 episode結果

|対象|revision|GPU|episode|terminal|打切り|平均距離 m|平均観測生存秒|平均jump|clear率|
|---|---|---|---:|---|---:|---:|---:|---:|---:|
|Kai|`cd49ea3813fd8ba0928a9a23ef6c9a0f2f0cd764`|NVIDIA A100-SXM4-40GB|5|collision:5|0|72.83|2.88|0|0.00|
|Eos|`3594047d69f476f1d01cf84c593e213fc3a4dfe0`|NVIDIA A100-SXM4-40GB|5|collision:5|0|72.83|2.88|1|0.00|
|Sol|`64235bef55dad29387dd16da7c90e038bf2f0972`|NVIDIA A100-SXM4-40GB|5|collision:5|0|85.48|3.37|0.80|0.00|
|Nox|`25e8f67d1b486c647222df3aac640d2d5d736bbe`|NVIDIA L4|5|collision:5|0|74.37|2.94|2.20|0.00|
|Lux|`78bf3c03d9147aeb30b641edfe0e30ed04887ca5`|NVIDIA RTX PRO 6000 Blackwell Server Edition|5|collision:5|0|72.83|2.88|0|0.00|
|Vega|`7aec49ae11a18741706da549ab626b9052795fe7`|NVIDIA RTX PRO 6000 Blackwell Server Edition|5|collision:5|0|109.93|4.31|1.80|0.00|
|rule|`control`|CPU: 13th Gen Intel(R) Core(TM) i7-13620H|5|time_limit:5|5|849.00|30.00|24.20|—|
|idle|`control`|CPU: 13th Gen Intel(R) Core(TM) i7-13620H|5|collision:5|0|72.83|2.88|0|0.00|

未測定対象: Sol-Reasoning（配布元401、forward 0）

## q3 推論・エラー

|対象|hardware|first system_one ms|後続/系列 p50 ms|forward calls|batch shape|late|欠落回答|response errors|runtime invalid|peak allocated GiB|peak reserved GiB|
|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
|Kai|NVIDIA A100-SXM4-40GB|1553.74|45.34|93|3x328×9, 3x336×13, 3x344×8, 3x352×7, 3x360×51, 3x376×3, 3x392×2|0|0|0|0|1.47|1.51|
|Eos|NVIDIA A100-SXM4-40GB|1747.55|95.14|64|3x328×7, 3x336×4, 3x344×4, 3x352×16, 3x360×14, 3x368×1, 3x376×9, 3x384×8, 3x392×1|3|0|0|0|2.07|2.19|
|Sol|NVIDIA A100-SXM4-40GB|1616.55|96.15|75|3x328×10, 3x344×6, 3x352×26, 3x360×14, 3x376×4, 3x384×6, 3x392×7, 3x400×1, 3x408×1|1|0|0|0|4.65|4.81|
|Nox|NVIDIA L4|1956.12|358.06|31|3x328×5, 3x344×2, 3x360×5, 3x376×9, 3x392×10|5|0|0|0|9.48|9.70|
|Lux|NVIDIA RTX PRO 6000 Blackwell Server Edition|1445.28|95.20|66|3x328×9, 3x336×3, 3x344×6, 3x352×29, 3x360×17, 3x384×2|0|0|0|0|17.03|17.20|
|Vega|NVIDIA RTX PRO 6000 Blackwell Server Edition|2175.43|359.04|45|3x328×5, 3x352×13, 3x360×10, 3x376×4, 3x384×3, 3x392×5, 3x408×3, 3x416×2|3|0|0|0|64.57|65.24|
|rule|CPU: 13th Gen Intel(R) Core(TM) i7-13620H|—|—|—|—|0|0|0|0|—|—|
|idle|CPU: 13th Gen Intel(R) Core(TM) i7-13620H|—|—|—|—|0|0|0|0|—|—|

## q64 episode結果

|対象|revision|GPU|episode|terminal|打切り|平均距離 m|平均観測生存秒|平均jump|clear率|
|---|---|---|---:|---|---:|---:|---:|---:|---:|
|Kai|`cd49ea3813fd8ba0928a9a23ef6c9a0f2f0cd764`|NVIDIA A100-SXM4-40GB|1|collision:1|0|73.00|2.88|0|0.00|
|Eos|`3594047d69f476f1d01cf84c593e213fc3a4dfe0`|NVIDIA A100-SXM4-40GB|1|collision:1|0|73.00|2.88|1|0.00|
|Sol|`64235bef55dad29387dd16da7c90e038bf2f0972`|NVIDIA A100-SXM4-40GB|1|collision:1|0|73.00|2.88|0|0.00|
|Nox|`25e8f67d1b486c647222df3aac640d2d5d736bbe`|NVIDIA L4|1|collision:1|0|73.00|2.88|0|0.00|
|Lux|`78bf3c03d9147aeb30b641edfe0e30ed04887ca5`|NVIDIA RTX PRO 6000 Blackwell Server Edition|1|collision:1|0|73.00|2.88|0|0.00|
|Vega|`7aec49ae11a18741706da549ab626b9052795fe7`|NVIDIA RTX PRO 6000 Blackwell Server Edition|1|collision:1|0|73.00|2.88|0|0.00|

未測定対象: Sol-Reasoning（配布元401、forward 0）

## q64 推論・エラー

|対象|hardware|first system_one ms|後続/系列 p50 ms|forward calls|batch shape|late|欠落回答|response errors|runtime invalid|peak allocated GiB|peak reserved GiB|
|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
|Kai|NVIDIA A100-SXM4-40GB|—|448.71|6|64x392×1, 64x400×1, 64x416×1, 64x424×3|1|0|0|0|2.74|3.88|
|Eos|NVIDIA A100-SXM4-40GB|—|891.90|3|64x392×1, 64x424×1, 64x456×1|1|0|0|0|5.78|8.88|
|Sol|NVIDIA A100-SXM4-40GB|—|1134.07|3|64x392×1, 64x424×2|1|0|0|0|8.33|10.50|
|Nox|NVIDIA L4|—|11379.65|1|64x392×1|1|0|0|0|16.25|17.62|
|Lux|NVIDIA RTX PRO 6000 Blackwell Server Edition|—|2413.42|2|64x392×1, 64x424×1|1|0|0|0|24.60|28.22|
|Vega|NVIDIA RTX PRO 6000 Blackwell Server Edition|—|8930.68|1|64x392×1|1|0|0|0|75.09|82.25|

## 未測定

- Sol-Reasoning: 配布元HTTP 401、固定revisionのcacheなし、System One呼び出し 0、neural forward 0。スコアや敗北としては扱いません。

検証済みtraceとrunner計測から生成。公開時点の対象status:
- Kai: measured
- Eos: measured
- Sol: measured
- Sol-Reasoning: unavailable
- Nox: measured
- Lux: measured
- Vega: measured
- rule: measured
- idle: measured
