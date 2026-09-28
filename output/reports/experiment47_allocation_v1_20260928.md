# 46本の割付 v1（2026-09-28）

「制約付きくじ引き」で作った。単純な無作為だと、偏ったときに処置の効果と
もともとの差を切り分けられない。条件を満たすくじが出るまで引き直している。
引き直した回数と採用シードを残すのは、後から同じ割付を再現するため。

- 採用シード：**20270135**（開始 20260928 から 9208 個目）
- 引用の判定：llm_experiment タブ（2026-09-15〜2026-09-27 の 295 行）
- 逆リンク追記の層：strata_backlink_20260925.csv（9/11〜9/16 の追記 23本。うち 9/15〜16 が 9本）
- タイトル変更（条件 g）：agentforce-for-sales-sdr-sales-coach・agentic-ai-guide・agentic-crm-pipeline-stagnation-detection
- 鮮度更新の訂正対象（条件 f）：agentforce-vibes・agentforce-features（2026-09-26 に agentforce-vibes の訂正は見送り。条件 f は2本のまま。判定で抜くのは agentforce-features だけ）
- プールから除外：agentforce-coworker（E37。見出し・FAQに及ぶ誤り訂正のため 2026-09-22 に除外）
- 対象：config/prompts_experiment.csv の 46 本

## チェック結果

| 条件 | 判定 | ①対照 | ②FAQのみ | ③リードのみ | ④両方 |
|---|---|---|---|---|---|
| a 各組11〜12本 | OK | 11 | 11 | 12 | 12 |
| b 逆リンク追記23本が組間で均等（実差 1） | OK | 6 | 6 | 5 | 6 |
| c 引用ありが最大差1（実差 1） | OK | 2 | 2 | 3 | 2 |
| d-1 2026-09公開が最大差1（実差 1） | OK | 2 | 1 | 2 | 2 |
| d-2 2026-07公開が最大差1（実差 1） | OK | 2 | 2 | 1 | 1 |
| e 9/15〜16 の追記9本が各組2〜3本（実差 1） | OK | 2 | 2 | 2 | 3 |
| f 鮮度更新の訂正対象（agentforce-vibes・agentforce-features）が各組に最大1本 | OK | 0 | 0 | 1 | 1 |
| g タイトル変更3本が各組に最大1本 | OK | 1 | 1 | 0 | 1 |

## 割付表

| # | id | url | 層 | 公開日 | 逆リンク追記 | 9/15〜16 の変更 | 引用あり | タイトル変更 | 訂正対象 | 組 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | E03 | https://cross-com.jp/agentic-crm-pipeline-kpi-monitoring/ | 古 | 2026-07-19 | — | — | — | — | — | ①対照 |
| 2 | E04 | https://cross-com.jp/agentforce-observability/ | 古 | 2026-07-24 | あり | あり | あり | — | — | ①対照 |
| 3 | E07 | https://cross-com.jp/agentforce-einstein-difference/ | 古 | 2026-08-01 | あり | — | — | — | — | ①対照 |
| 4 | E10 | https://cross-com.jp/agentforce-service-agent/ | 古 | 2026-08-04 | あり | — | — | — | — | ①対照 |
| 5 | E17 | https://cross-com.jp/agentforce-security-risk-design/ | 中 | 2026-08-13 | あり | — | — | — | — | ①対照 |
| 6 | E18 | https://cross-com.jp/agentforce-usecase-selection/ | 中 | 2026-08-13 | あり | — | — | — | — | ①対照 |
| 7 | E25 | https://cross-com.jp/agentforce-marketing/ | 中 | 2026-08-17 | — | — | — | — | — | ①対照 |
| 8 | E29 | https://cross-com.jp/agentic-ai-guide/ | 中 | 2026-08-19 | — | — | — | あり | — | ①対照 |
| 9 | E31 | https://cross-com.jp/agentforce-employee-agent/ | 中 | 2026-08-22 | あり | あり | あり | — | — | ①対照 |
| 10 | E42 | https://cross-com.jp/agentforce-sales-meeting/ | 新 | 2026-09-02 | — | — | — | — | — | ①対照 |
| 11 | E43 | https://cross-com.jp/agentforce-no-code-scope/ | 新 | 2026-09-03 | — | — | — | — | — | ①対照 |
| 12 | E01 | https://cross-com.jp/agentforce-for-sales-sdr-sales-coach/ | 古 | 2026-07-03 | あり | — | あり | あり | — | ②FAQのみ |
| 13 | E02 | https://cross-com.jp/agentforce-retention/ | 古 | 2026-07-06 | あり | — | — | — | — | ②FAQのみ |
| 14 | E09 | https://cross-com.jp/agentforce-mcp/ | 古 | 2026-08-02 | あり | — | — | — | — | ②FAQのみ |
| 15 | E13 | https://cross-com.jp/agentforce-testing-center/ | 古 | 2026-08-06 | あり | あり | — | — | — | ②FAQのみ |
| 16 | E15 | https://cross-com.jp/agentforce-certification/ | 中 | 2026-08-11 | — | — | — | — | — | ②FAQのみ |
| 17 | E16 | https://cross-com.jp/agentforce-chatgpt-copilot-comparison/ | 中 | 2026-08-12 | — | — | — | — | — | ②FAQのみ |
| 18 | E19 | https://cross-com.jp/agentforce-usage/ | 中 | 2026-08-14 | あり | — | あり | — | — | ②FAQのみ |
| 19 | E20 | https://cross-com.jp/agentforce-use-cases/ | 中 | 2026-08-14 | あり | あり | — | — | — | ②FAQのみ |
| 20 | E33 | https://cross-com.jp/agentforce-sales-roleplay/ | 新 | 2026-08-24 | — | — | — | — | — | ②FAQのみ |
| 21 | E40 | https://cross-com.jp/agentforce-lost-deal-analysis/ | 新 | 2026-08-31 | — | — | — | — | — | ②FAQのみ |
| 22 | E41 | https://cross-com.jp/agentforce-sales-dependency/ | 新 | 2026-09-01 | — | — | — | — | — | ②FAQのみ |
| 23 | E05 | https://cross-com.jp/agentforce-roi/ | 古 | 2026-07-26 | あり | — | — | — | — | ③リードのみ |
| 24 | E12 | https://cross-com.jp/agentforce-features/ | 古 | 2026-08-06 | — | — | — | — | 対象 | ③リードのみ |
| 25 | E14 | https://cross-com.jp/agentforce-in-slack/ | 古 | 2026-08-08 | — | — | — | — | — | ③リードのみ |
| 26 | E22 | https://cross-com.jp/agentforce-reasoning-control/ | 中 | 2026-08-15 | あり | — | — | — | — | ③リードのみ |
| 27 | E28 | https://cross-com.jp/revops-guide/ | 中 | 2026-08-19 | あり | あり | あり | — | — | ③リードのみ |
| 28 | E30 | https://cross-com.jp/einstein-trust-layer/ | 中 | 2026-08-21 | あり | — | あり | — | — | ③リードのみ |
| 29 | E32 | https://cross-com.jp/tableau-ai/ | 新 | 2026-08-23 | — | — | — | — | — | ③リードのみ |
| 30 | E35 | https://cross-com.jp/agentforce-deal-notes/ | 新 | 2026-08-25 | — | — | — | — | — | ③リードのみ |
| 31 | E36 | https://cross-com.jp/agentforce-voice/ | 新 | 2026-08-26 | — | — | あり | — | — | ③リードのみ |
| 32 | E38 | https://cross-com.jp/agentforce-subagents/ | 新 | 2026-08-27 | あり | あり | — | — | — | ③リードのみ |
| 33 | E44 | https://cross-com.jp/agentforce-data-volume/ | 新 | 2026-09-04 | — | — | — | — | — | ③リードのみ |
| 34 | E46 | https://cross-com.jp/agentforce-permission-set/ | 新 | 2026-09-06 | — | — | — | — | — | ③リードのみ |
| 35 | E06 | https://cross-com.jp/agentforce-rag/ | 古 | 2026-07-29 | あり | — | — | — | — | ④両方 |
| 36 | E08 | https://cross-com.jp/agentforce-small-business/ | 古 | 2026-08-02 | あり | — | あり | — | — | ④両方 |
| 37 | E11 | https://cross-com.jp/agentforce-vibes/ | 古 | 2026-08-05 | — | — | — | — | 対象 | ④両方 |
| 38 | E21 | https://cross-com.jp/agentforce-agent-script/ | 中 | 2026-08-14 | あり | — | — | — | — | ④両方 |
| 39 | E23 | https://cross-com.jp/buyer-enablement/ | 中 | 2026-08-16 | あり | あり | — | — | — | ④両方 |
| 40 | E24 | https://cross-com.jp/salesforce-ai/ | 中 | 2026-08-17 | — | — | — | — | — | ④両方 |
| 41 | E26 | https://cross-com.jp/salesforce-data-360/ | 中 | 2026-08-18 | あり | あり | — | — | — | ④両方 |
| 42 | E27 | https://cross-com.jp/hyper-personalization/ | 中 | 2026-08-18 | あり | あり | — | — | — | ④両方 |
| 43 | E34 | https://cross-com.jp/agentic-crm-pipeline-stagnation-detection/ | 新 | 2026-08-25 | — | — | あり | あり | — | ④両方 |
| 44 | E39 | https://cross-com.jp/sfa-teichaku/ | 新 | 2026-08-30 | — | — | — | — | — | ④両方 |
| 45 | E45 | https://cross-com.jp/agentforce-data-library/ | 新 | 2026-09-05 | — | — | — | — | — | ④両方 |
| 46 | E47 | https://cross-com.jp/agentforce-proposal-review/ | 新 | 2026-09-07 | — | — | — | — | — | ④両方 |

## 判定時の集計（込み／訂正対象を抜き）

判定は llm_experiment のみで行う（引用プローブは実験期間中は不使用）。
訂正対象はアフター期間の本文に「処置」と「訂正」の両方が乗る。
判定は次の2通りを必ず並べて出し、結論が食い違えば訂正の影響として扱う。

- **込み**：46本すべて
- **agentforce-features 抜き**：訂正が入る1本を除いた45本
  （2026-09-26 に agentforce-vibes の訂正は見送り。条件 f は2本のまま）
- llm_experiment の experiment_flag=watch の行（E37）は数えない

```
python experiment_2x2/summarize.py --before <ビフォー開始>:<ビフォー終了> --after <アフター開始>:<アフター終了>
```
（summarize.py がモデルごとに両方を出す。対象は pool.APPLIED_CORRECTION_SLUGS）

## 再現方法

```
python experiment_2x2/allocate_47.py --seed-start 20270135 --cited-from 2026-09-15 --cited-to 2026-09-27
```

※ c の判定は観測データに依存する。同じ割付を出すには、同じ期間の
llm_experiment を参照すること（後から行が増えると結果が変わりうる）。