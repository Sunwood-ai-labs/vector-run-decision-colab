# 正式比較から除外した記録

`kai/20261004T161431Z` はKaiの初回測定記録です。公開準備で通常のキャッシュパスを置換し、ゲームJSONを上書きしたため、公開ファイルのSHA-256とrunnerが測定時に記録したSHA-256が一致しません。置換前の原本は見つからず、物理traceが不変だったことも証明できません。

`verification.json` に両方のハッシュ、確認できた変換箇所、`physicalTraceUnchanged: null`、`aggregateEligible: false`を記録しています。この記録は正式集計と比較動画に使用しません。再測定では取得したゲーム・runner JSONを加工せず保存します。
