# LLMO効果測定実験 7週目の集計(2026-10-26〜2026-11-01)

- 生成日: 2026-11-02(自動・毎週月曜) / 出典: Google Sheets `llm_experiment`(同期間 95行)
- 期間の区分: アフター
- 対象: プール46本(config/prompts_experiment.csv)。プール外の記事の行 3件は数えていない
- 率の分母は観測できた回数(欠測を除く)
- Gemini の呼び出し回数は `data/raw` の `attempts`(再試行込み)。attempts の無い raw がある日は下限(≥)で示す

## 1. 全体

| モデル | 観測行 | 欠測 | 有効観測 | cited_article=1 | 記事引用率 | cited_domain=1 | ドメイン引用率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Gemini | 95 | 2 | 93 | 16 | 17.2% | 19 | 20.4% |
| Claude | 0 | 0 | 0 | 0 | — | 0 | — |

- **記事URLが1回でも出た記事: 11本 / 46本**(Gemini 11本・Claude 0本・両方 0本)
  - Claude は 2026-10-06 から計画的に停止（費用ゼロ方針・本田さん決定）。この週の Claude の観測は無い（欠測ではない）
  - E08(agentforce-small-business)、E15(agentforce-certification)、E19(agentforce-usage)、E21(agentforce-agent-script)、E24(salesforce-ai)、E28(revops-guide)、E30(einstein-trust-layer)、E31(agentforce-employee-agent)、E32(tableau-ai)、E35(agentforce-deal-notes)、E36(agentforce-voice)
- cross-com.jp のどれかのURLが1回でも出た記事: 13本 / 46本

## 1-2. 組ごとの欠測(実験の Gemini・本数のみ)

欠測(error のある行)の本数だけを出す。引用率・差は出さない(11/2 まで組ごとの結果を見ないルール)。

| 期間 | ①対照 | ②FAQのみ | ③リードのみ | ④両方 | 組の間の差 |
|---|---:|---:|---:|---:|---:|
| この週(10/26〜11/01) | 1 | 0 | 0 | 1 | 1 |
| アフター期間の累計(10/06〜11/01) | 7 | 5 | 5 | 7 | 2 |


欠測の種類ごと(本数):

| 期間 | 種類 | ①対照 | ②FAQのみ | ③リードのみ | ④両方 | 計 |
|---|---|---:|---:|---:|---:|---:|
| この週(10/26〜11/01) | 503 | 1 | 0 | 0 | 1 | 2 |
| アフター期間の累計(10/06〜11/01) | 503 | 5 | 5 | 3 | 7 | 20 |
| アフター期間の累計(10/06〜11/01) | 429 | 2 | 0 | 2 | 0 | 4 |

## 2. Gemini の1日あたり呼び出し数と欠測

| 日付 | 曜 | 日次 | 月次 | 実験 | 合計 / 20 | 実験の欠測 | 枠切れ | 503 | 投げずに記録 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-10-26 | 月 | 0 | 0 | 14 | 14 | 0 | 0 | 0 | 0 |
| 2026-10-27 | 火 | 0 | 0 | 14 | 14 | 0 | 0 | 0 | 0 |
| 2026-10-28 | 水 | 0 | 0 | 18 | 18 | 0 | 0 | 0 | 0 |
| 2026-10-29 | 木 | 0 | 0 | 16 | 16 | 0 | 0 | 0 | 0 |
| 2026-10-30 | 金 | 0 | 0 | 14 | 14 | 0 | 0 | 0 | 0 |
| 2026-10-31 | 土 | 0 | 0 | 20 | 20 | 2 | 0 | 2 | 0 |
| 2026-11-01 | 日 | 0 | 0 | 14 | 14 | 0 | 0 | 0 | 0 |

- 実験 Gemini の欠測の内訳: 枠切れ(429)0件・503 2件・投げずに記録(日次・月次の実消費で枠が足りない日)0件
- 合計には 429 で拒否された回も含む(投げた回数であり、枠を消費した回数ではない)

## 3. 記事ごと

「観測」は観測行数(欠測を含む)、「記事」は cited_article=1、「ドメイン」は cited_domain=1 の回数。

| ID | 層 | 記事 | Gemini 観測 | 記事 | ドメイン | 欠測 | Claude 観測 | 記事 | ドメイン | 欠測 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| E01 | 古 | agentforce-for-sales-sdr-sales-coach | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E02 | 古 | agentforce-retention | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E03 | 古 | agentic-crm-pipeline-kpi-monitoring | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E04 | 古 | agentforce-observability | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E05 | 古 | agentforce-roi | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E06 | 古 | agentforce-rag | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E07 | 古 | agentforce-einstein-difference | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E08 | 古 | agentforce-small-business | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| E09 | 古 | agentforce-mcp | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E10 | 古 | agentforce-service-agent | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E11 | 古 | agentforce-vibes | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E12 | 古 | agentforce-features | 2 | 0 | 2 | 0 | 0 | 0 | 0 | 0 |
| E13 | 古 | agentforce-testing-center | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E14 | 古 | agentforce-in-slack | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E15 | 中 | agentforce-certification | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| E16 | 中 | agentforce-chatgpt-copilot-comparison | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E17 | 中 | agentforce-security-risk-design | 2 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| E18 | 中 | agentforce-usecase-selection | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E19 | 中 | agentforce-usage | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| E20 | 中 | agentforce-use-cases | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E21 | 中 | agentforce-agent-script | 2 | 1 | 1 | 1 | 0 | 0 | 0 | 0 |
| E22 | 中 | agentforce-reasoning-control | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E23 | 中 | buyer-enablement | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E24 | 中 | salesforce-ai | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| E25 | 中 | agentforce-marketing | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E26 | 中 | salesforce-data-360 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E27 | 中 | hyper-personalization | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E28 | 中 | revops-guide | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| E29 | 中 | agentic-ai-guide | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E30 | 中 | einstein-trust-layer | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| E31 | 中 | agentforce-employee-agent | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| E32 | 新 | tableau-ai | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| E33 | 新 | agentforce-sales-roleplay | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E34 | 新 | agentic-crm-pipeline-stagnation-detection | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E35 | 新 | agentforce-deal-notes | 3 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| E36 | 新 | agentforce-voice | 3 | 3 | 3 | 0 | 0 | 0 | 0 | 0 |
| E38 | 新 | agentforce-subagents | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E39 | 新 | sfa-teichaku | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E40 | 新 | agentforce-lost-deal-analysis | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E41 | 新 | agentforce-sales-dependency | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E42 | 新 | agentforce-sales-meeting | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E43 | 新 | agentforce-no-code-scope | 2 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| E44 | 新 | agentforce-data-volume | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E45 | 新 | agentforce-data-library | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E46 | 新 | agentforce-permission-set | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E47 | 新 | agentforce-proposal-review | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## 4. この週の介入(output/interventions.csv)

この週に実施した介入はない(日付の分かっているもの)。

日付が1日に定まらない介入(どの週に効いたか分からない):
- I-05 タイトル・メタディスクリプション改修(9/15 以降の変更は0件。記録のみ)(サイト(メタ)・本田さん(手動))

## 5. 参考:回答本文の社名言及(mentioned_v2)

社名は記事が引用されなくても出るため、処置の効果の判定には使わない。ブランド想起の目安として並べる。表記ゆれ(Cross-Com・CrossCom・クロス・コム など)を含む(2026-10-01 修正。9/15 以降は遡って再計算済み)。

- Gemini: 0 / 93(0.0%)
- Claude: 0 / 0(—)

## 5-2. 参考:並びによる誤引用の見張り(実験の Gemini・4本)

架空の例(主語のない「ある会社では」型)の直後に「当社では…」が続く並びがある4本。AI が当社の支援の例と読むおそれがある(Perplexity の誤引用の原因)。E33 は 2026-10-18 に修正済み、ほかの3本は 2027-01-01 以降に修正。回答に社名(mentioned_v2 の表記)が出た件数を出す。**組ごとの比較はしない(判定には使わない)**

- E33 agentforce-sales-roleplay:0件 / 回答 2件
- E09 agentforce-mcp:0件 / 回答 2件
- E47 agentforce-proposal-review:0件 / 回答 2件
- E42 agentforce-sales-meeting:0件 / 回答 2件
- 計 0件
