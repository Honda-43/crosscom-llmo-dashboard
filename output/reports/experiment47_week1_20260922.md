# LLMO効果測定実験 ビフォー1週目の集計(2026-09-15〜09-21)

- 集計日: 2026-09-22 / 出典: Google Sheets `llm_experiment`(同期間 182行)
- **確定: 2026-09-22**(Gemini の cited_article 率 17.8%・13/73。E37 を含む47本での集計)
- Gemini の呼び出し回数は `data/raw` の `attempts`(再試行込み)から数えた。9/18 以前の raw には `attempts` が無いため、その日は行数(下限)で示す
- 率の分母は観測できた回数(欠測を除く)

## 1. 全体

| モデル | 観測行 | 欠測 | 有効観測 | cited_article=1 | cited_article 率 | mentioned=1 |
|---|---:|---:|---:|---:|---:|---:|
| Gemini | 88 | 15 | 73 | 13 | 17.8% | 0 |
| Claude | 94 | 0 | 94 | 3 | 3.2% | 0 |

- **記事URLが1回でも出た記事: 8本 / 47本**(Gemini 7本・Claude 2本・両方 1本)
  - E01(agentforce-for-sales-sdr-sales-coach)、E08(agentforce-small-business)、E19(agentforce-usage)、E30(einstein-trust-layer)、E31(agentforce-employee-agent)、E34(agentic-crm-pipeline-stagnation-detection)、E36(agentforce-voice)、E37(agentforce-coworker)
- Gemini の有効観測が0回の記事: 2本(E10、E11)

## 2. Gemini の1日あたり呼び出し数と枠切れ

| 日付 | 曜 | 日次 | 実験 | 合計 / 20 | 実験の欠測 | うち枠切れ(PerDay) | うち503 |
|---|---|---:|---:|---:|---:|---:|---:|
| 2026-09-15 | 火 | ≥7 | ≥11 | ≥18 | 0 | 0 | 0 |
| 2026-09-16 | 水 | 0 | ≥13 | ≥13 | 1 | 0 | 1 |
| 2026-09-17 | 木 | ≥7 | ≥5 | ≥12 | 0 | 0 | 0 |
| 2026-09-18 | 金 | 0 | ≥18 | ≥18 | 4 | 0 | 4 |
| 2026-09-19 | 土 | 17 | 13 | 30 | 10 | 10 | 0 |
| 2026-09-20 | 日 | 0 | 15 | 15 | 0 | 0 | 0 |
| 2026-09-21 | 月 | 0 | 14 | 14 | 0 | 0 | 0 |

- 9/19 の合計30は、429 で拒否された10回も数えている(投げた回数であり、枠を消費した回数ではない)
- **枠切れ(PerDay)の欠測: 計10件**。すべて 9/19(土)。日次が 503 の再試行で17回投げ、実験に3回しか残らなかった(f6c2a0b で、日次の実消費を見てから本数を決める方式に修正済み)
- 9/15〜9/18 は旧割当(曜日ごとのID範囲)、9/19 から開始日基準の巡回。旧割当と巡回の境目で、Gemini の観測回数は記事ごとに1〜2回とばらつく(E42〜E47 は1回)

## 3. 記事ごと

「観測」は観測行数(欠測を含む)、「引用」は cited_article=1、「言及」は mentioned=1 の回数。※ は実験日誌の決定で 9/17 以降の観測だけをビフォーに使う記事(この表は 9/15 分も含む)。

| ID | 層 | 記事 | Gemini 観測 | 引用 | 言及 | 欠測 | Claude 観測 | 引用 | 言及 | 欠測 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| E01 | 古 | agentforce-for-sales-sdr-sales-coach | 2 | 2 | 0 | 0 | 2 | 0 | 0 | 0 |
| E02 | 古 | agentforce-retention | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E03 | 古 | agentic-crm-pipeline-kpi-monitoring | 2 | 0 | 0 | 1 | 2 | 0 | 0 | 0 |
| E04 | 古 | agentforce-observability※ | 2 | 0 | 0 | 1 | 2 | 0 | 0 | 0 |
| E05 | 古 | agentforce-roi | 2 | 0 | 0 | 1 | 2 | 0 | 0 | 0 |
| E06 | 古 | agentforce-rag | 2 | 0 | 0 | 1 | 2 | 0 | 0 | 0 |
| E07 | 古 | agentforce-einstein-difference | 2 | 0 | 0 | 1 | 2 | 0 | 0 | 0 |
| E08 | 古 | agentforce-small-business | 2 | 0 | 0 | 1 | 2 | 1 | 0 | 0 |
| E09 | 古 | agentforce-mcp | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E10 | 古 | agentforce-service-agent | 2 | 0 | 0 | 2 | 2 | 0 | 0 | 0 |
| E11 | 古 | agentforce-vibes | 2 | 0 | 0 | 2 | 2 | 0 | 0 | 0 |
| E12 | 古 | agentforce-features | 2 | 0 | 0 | 1 | 2 | 0 | 0 | 0 |
| E13 | 古 | agentforce-testing-center | 2 | 0 | 0 | 1 | 2 | 0 | 0 | 0 |
| E14 | 古 | agentforce-in-slack | 2 | 0 | 0 | 1 | 2 | 0 | 0 | 0 |
| E15 | 中 | agentforce-certification | 2 | 0 | 0 | 1 | 2 | 0 | 0 | 0 |
| E16 | 中 | agentforce-chatgpt-copilot-comparison | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E17 | 中 | agentforce-security-risk-design | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E18 | 中 | agentforce-usecase-selection | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E19 | 中 | agentforce-usage | 2 | 1 | 0 | 0 | 2 | 0 | 0 | 0 |
| E20 | 中 | agentforce-use-cases | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E21 | 中 | agentforce-agent-script | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E22 | 中 | agentforce-reasoning-control | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E23 | 中 | buyer-enablement | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E24 | 中 | salesforce-ai | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E25 | 中 | agentforce-marketing | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E26 | 中 | salesforce-data-360 | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E27 | 中 | hyper-personalization※ | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E28 | 中 | revops-guide※ | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E29 | 中 | agentic-ai-guide | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E30 | 中 | einstein-trust-layer | 2 | 2 | 0 | 0 | 2 | 0 | 0 | 0 |
| E31 | 中 | agentforce-employee-agent | 2 | 2 | 0 | 0 | 2 | 0 | 0 | 0 |
| E32 | 新 | tableau-ai | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E33 | 新 | agentforce-sales-roleplay | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E34 | 新 | agentic-crm-pipeline-stagnation-detection | 2 | 2 | 0 | 0 | 2 | 0 | 0 | 0 |
| E35 | 新 | agentforce-deal-notes | 2 | 0 | 0 | 1 | 2 | 0 | 0 | 0 |
| E36 | 新 | agentforce-voice | 2 | 2 | 0 | 0 | 2 | 0 | 0 | 0 |
| E37 | 新 | agentforce-coworker | 2 | 2 | 0 | 0 | 2 | 2 | 0 | 0 |
| E38 | 新 | agentforce-subagents | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E39 | 新 | sfa-teichaku | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E40 | 新 | agentforce-lost-deal-analysis | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E41 | 新 | agentforce-sales-dependency | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E42 | 新 | agentforce-sales-meeting | 1 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E43 | 新 | agentforce-no-code-scope | 1 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E44 | 新 | agentforce-data-volume | 1 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E45 | 新 | agentforce-data-library | 1 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E46 | 新 | agentforce-permission-set | 1 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| E47 | 新 | agentforce-proposal-review | 1 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |

## 4. 読むときの注意

- ※の3本の 9/15・9/16 の観測は 2行。ビフォーの基準値を出すときは除く(output/reports/experiment47_diary.md)
- Claude は 月・木 の47本なので、この週は 9/17(木)・9/21(月)の2回
- 欠測は率の分母から外している。欠測を「引用なし」と数えると率が下がる
