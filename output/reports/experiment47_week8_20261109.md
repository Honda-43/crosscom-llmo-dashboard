# LLMO効果測定実験 8週目の集計(2026-11-02〜2026-11-08)

- 生成日: 2026-11-09(自動・毎週月曜) / 出典: Google Sheets `llm_experiment`(同期間 96行)
- 期間の区分: アフター
- 対象: プール46本(config/prompts_experiment.csv)。プール外の記事の行 2件は数えていない
- 率の分母は観測できた回数(欠測を除く)
- Gemini の呼び出し回数は `data/raw` の `attempts`(再試行込み)。attempts の無い raw がある日は下限(≥)で示す

## 1. 全体

| モデル | 観測行 | 欠測 | 有効観測 | cited_article=1 | 記事引用率 | cited_domain=1 | ドメイン引用率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Gemini | 96 | 4 | 92 | 17 | 18.5% | 19 | 20.7% |
| Claude | 0 | 0 | 0 | 0 | — | 0 | — |

- **記事URLが1回でも出た記事: 12本 / 46本**(Gemini 12本・Claude 0本・両方 0本)
  - Claude は 2026-10-06 から計画的に停止（費用ゼロ方針・本田さん決定）。この週の Claude の観測は無い（欠測ではない）
  - E01(agentforce-for-sales-sdr-sales-coach)、E08(agentforce-small-business)、E15(agentforce-certification)、E19(agentforce-usage)、E21(agentforce-agent-script)、E23(buyer-enablement)、E24(salesforce-ai)、E30(einstein-trust-layer)、E31(agentforce-employee-agent)、E32(tableau-ai)、E36(agentforce-voice)、E45(agentforce-data-library)
- cross-com.jp のどれかのURLが1回でも出た記事: 14本 / 46本

## 1-2. 組ごとの欠測(実験の Gemini・本数のみ)

欠測(error のある行)の本数だけを出す。引用率・差は出さない(11/2 まで組ごとの結果を見ないルール)。

| 期間 | ①対照 | ②FAQのみ | ③リードのみ | ④両方 | 組の間の差 |
|---|---:|---:|---:|---:|---:|
| この週(11/02〜11/08) | 1 | 0 | 1 | 2 | 2 |
| アフター期間の累計(10/06〜11/08) | 8 | 5 | 6 | 9 | 4 |

- ⚠️ **アフター期間の累計で、組の間の欠測の差が4本(警告は3本以上)。**欠測が特定の組に偏ると、組の比較の母数がずれる。欠測の理由(第2節)と、取り直しの枠を確かめる

欠測の種類ごと(本数):

| 期間 | 種類 | ①対照 | ②FAQのみ | ③リードのみ | ④両方 | 計 |
|---|---|---:|---:|---:|---:|---:|
| この週(11/02〜11/08) | 503 | 1 | 0 | 1 | 2 | 4 |
| アフター期間の累計(10/06〜11/08) | 503 | 6 | 5 | 4 | 9 | 24 |
| アフター期間の累計(10/06〜11/08) | 429 | 2 | 0 | 2 | 0 | 4 |

## 2. Gemini の1日あたり呼び出し数と欠測

| 日付 | 曜 | 日次 | 月次 | 実験 | 合計 / 20 | 実験の欠測 | 枠切れ | 503 | 投げずに記録 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-11-02 | 月 | 0 | 0 | 20 | 20 | 4 | 0 | 4 | 0 |
| 2026-11-03 | 火 | 0 | 0 | 14 | 14 | 0 | 0 | 0 | 0 |
| 2026-11-04 | 水 | 0 | 0 | 14 | 14 | 0 | 0 | 0 | 0 |
| 2026-11-05 | 木 | 0 | 0 | 14 | 14 | 0 | 0 | 0 | 0 |
| 2026-11-06 | 金 | 0 | 0 | 14 | 14 | 0 | 0 | 0 | 0 |
| 2026-11-07 | 土 | 0 | 0 | 16 | 16 | 0 | 0 | 0 | 0 |
| 2026-11-08 | 日 | 0 | 0 | 14 | 14 | 0 | 0 | 0 | 0 |

- 実験 Gemini の欠測の内訳: 枠切れ(429)0件・503 4件・投げずに記録(日次・月次の実消費で枠が足りない日)0件
- 合計には 429 で拒否された回も含む(投げた回数であり、枠を消費した回数ではない)

## 3. 記事ごと

「観測」は観測行数(欠測を含む)、「記事」は cited_article=1、「ドメイン」は cited_domain=1 の回数。

| ID | 層 | 記事 | Gemini 観測 | 記事 | ドメイン | 欠測 | Claude 観測 | 記事 | ドメイン | 欠測 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| E01 | 古 | agentforce-for-sales-sdr-sales-coach | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
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
| E12 | 古 | agentforce-features | 2 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| E13 | 古 | agentforce-testing-center | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E14 | 古 | agentforce-in-slack | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E15 | 中 | agentforce-certification | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| E16 | 中 | agentforce-chatgpt-copilot-comparison | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E17 | 中 | agentforce-security-risk-design | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E18 | 中 | agentforce-usecase-selection | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E19 | 中 | agentforce-usage | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| E20 | 中 | agentforce-use-cases | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E21 | 中 | agentforce-agent-script | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| E22 | 中 | agentforce-reasoning-control | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E23 | 中 | buyer-enablement | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| E24 | 中 | salesforce-ai | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| E25 | 中 | agentforce-marketing | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E26 | 中 | salesforce-data-360 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E27 | 中 | hyper-personalization | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E28 | 中 | revops-guide | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E29 | 中 | agentic-ai-guide | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E30 | 中 | einstein-trust-layer | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| E31 | 中 | agentforce-employee-agent | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| E32 | 新 | tableau-ai | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| E33 | 新 | agentforce-sales-roleplay | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E34 | 新 | agentic-crm-pipeline-stagnation-detection | 2 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| E35 | 新 | agentforce-deal-notes | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E36 | 新 | agentforce-voice | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| E38 | 新 | agentforce-subagents | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E39 | 新 | sfa-teichaku | 3 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| E40 | 新 | agentforce-lost-deal-analysis | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E41 | 新 | agentforce-sales-dependency | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E42 | 新 | agentforce-sales-meeting | 3 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| E43 | 新 | agentforce-no-code-scope | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E44 | 新 | agentforce-data-volume | 2 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| E45 | 新 | agentforce-data-library | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| E46 | 新 | agentforce-permission-set | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E47 | 新 | agentforce-proposal-review | 2 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |

## 4. この週の介入(output/interventions.csv)

| 日付 | ID | 内容 | 範囲 | プール46本に触れる |
|---|---|---|---|---|
| 2026-11-08 | I-56 | 19:50:03 JST 新規記事の公開 post 9445「ソリューション営業のAI活用｜任せる業務・任せない判断と支援会社の選び方」https://cross-com.jp/solution-sales-ai/。目次・記事内CTA（上下）・バナー2本・Yoast FAQ ブロック・D-39 結論要約。アイキャッチ（WebP・media 9555）を設定し、表示はページ設定で非表示・シェアボタン非表示 | new_article | no |
| 2026-11-08 | I-57 | 19:50:23 JST 新規記事の公開 post 9446「業務設計から頼むSalesforce導入支援｜要件定義の範囲と選び方」https://cross-com.jp/business-design-implementation-support/。目次・記事内CTA（上下）・バナー2本・Yoast FAQ ブロック・D-39 結論要約。アイキャッチ（WebP・media 9556）を設定し、表示はページ設定で非表示・シェアボタン非表示 | new_article | no |
| 2026-11-08 | I-58 | 20:08:10 JST 新規記事の公開 post 9447「ITコンサルティング会社のAgentforce活用｜8つの業務と人に残す判断」https://cross-com.jp/it-consulting-agentforce/。目次・記事内CTA（上下）・バナー2本・Yoast FAQ ブロック・D-39 結論要約・D-46 の図2枚（C2-03・C3-01）。アイキャッチ（WebP・media 9568）を設定し、表示はページ設定で非表示・シェアボタン非表示 | new_article | no |
| 2026-11-08 | I-59 | 20:08:29 JST 新規記事の公開 post 9448「住宅業界の建材営業のAI活用｜Agentforceに任せる5業務と任せない判断」https://cross-com.jp/building-materials-sales-ai/。目次・記事内CTA（上下）・バナー2本・Yoast FAQ ブロック・D-39 結論要約・D-46 の図2枚（C2-04・C3-03）。アイキャッチ（WebP・media 9569）を設定し、表示はページ設定で非表示・シェアボタン非表示 | new_article | no |
| 2026-11-08 | I-60 | 20:08:48 JST 新規記事の公開 post 9449「営業のAI活用事例｜自社の営業でAgentforceを使ってわかったこと」https://cross-com.jp/sales-ai-case-study/。目次・記事内CTA（上下）・バナー2本・Yoast FAQ ブロック・D-39 結論要約・D-46 の図2枚（C1-12・C1-08）。アイキャッチ（WebP・media 9570）を設定し、表示はページ設定で非表示・シェアボタン非表示 | new_article | no |
| 2026-11-08 | I-61 | 20:55:42 JST（リビジョン 9571）post 8100 sales-back-office：記事内CTA（サービス資料）の説明文から「導入企業のBefore / After・」を外した（1か所）。サービス資料に該当ページが無く、Agentforce の顧客導入は0件のため。説明文の他・リンク・ボタンは不変 | site_content | no |
| 2026-11-08 | I-62 | 20:56:00 JST（リビジョン 9572）post 7717 agentforce-japanese：記事内CTA（サービス資料）の説明文から「導入企業のBefore / After・」を外した（1か所）。サービス資料に該当ページが無く、Agentforce の顧客導入は0件のため。説明文の他・リンク・ボタンは不変 | site_content | no |
| 2026-11-08 | I-63 | 20:56:19 JST（リビジョン 9573）post 8086 salesforce-partner：記事内CTA（サービス資料）の説明文から「導入企業のBefore / After・」を外した（2か所）。サービス資料に該当ページが無く、Agentforce の顧客導入は0件のため。説明文の他・リンク・ボタンは不変 | site_content | no |
| 2026-11-08 | I-64 | 20:56:36 JST（リビジョン 9574）post 7218 agentforce-similar-deals：記事内CTA（サービス資料）の説明文から「導入企業のBefore / After・」を外した（1か所）。サービス資料に該当ページが無く、Agentforce の顧客導入は0件のため。説明文の他・リンク・ボタンは不変 | site_content | no |
| 2026-11-08 | I-65 | 20:56:55 JST（リビジョン 9575）post 7209 agentforce-delivery-answer：記事内CTA（サービス資料）の説明文から「導入企業のBefore / After・」を外した（1か所）。サービス資料に該当ページが無く、Agentforce の顧客導入は0件のため。説明文の他・リンク・ボタンは不変 | site_content | no |
| 2026-11-08 | I-66 | 20:57:13 JST（リビジョン 9576）post 7980 ai-agent-implementation-support：記事内CTA（サービス資料）の説明文から「導入企業のBefore / After・」を外した（2か所）。サービス資料に該当ページが無く、Agentforce の顧客導入は0件のため。説明文の他・リンク・ボタンは不変 | site_content | no |
| 2026-11-08 | I-67 | 20:57:32 JST（リビジョン 9577）post 6194 agentforce-pricing：記事内CTA（サービス資料）の説明文から「導入企業のBefore / After・」を外した（1か所）。サービス資料に該当ページが無く、Agentforce の顧客導入は0件のため。説明文の他・リンク・ボタンは不変 | site_content | no |
| 2026-11-08 | I-68 | 20:57:50 JST（リビジョン 9578）post 6102 agentforce-support-company：記事内CTA（サービス資料）の説明文から「導入企業のBefore / After・」を外した（2か所）。サービス資料に該当ページが無く、Agentforce の顧客導入は0件のため。説明文の他・リンク・ボタンは不変 | site_content | no |
| 2026-11-08 | I-69 | 20:59:51 JST（リビジョン 9579）post 9447 it-consulting-agentforce：①H2① 概観文に1文を足し sales-ai-case-study へ「導入前と後の変化」でリンク ②H2⑪ の末尾に1文を足し solution-sales-ai へ「ソリューション営業」でリンク ③図の直前の主張の文2か所を前の文とつなげて言い直した（「ます」の3連続を避ける・意味は同じ） | site_content | no |
| 2026-11-08 | I-70 | 21:00:09 JST（リビジョン 9580）post 9448 building-materials-sales-ai：落とし穴② の最後の段落で、図の直前の主張の文を2文目に移し「〜送りましょう」で締めた（意味は同じ） | site_content | no |

日付が1日に定まらない介入(どの週に効いたか分からない):
- I-05 タイトル・メタディスクリプション改修(9/15 以降の変更は0件。記録のみ)(サイト(メタ)・本田さん(手動))

## 5. 参考:回答本文の社名言及(mentioned_v2)

社名は記事が引用されなくても出るため、処置の効果の判定には使わない。ブランド想起の目安として並べる。表記ゆれ(Cross-Com・CrossCom・クロス・コム など)を含む(2026-10-01 修正。9/15 以降は遡って再計算済み)。

- Gemini: 0 / 92(0.0%)
- Claude: 0 / 0(—)

## 5-2. 参考:並びによる誤引用の見張り(実験の Gemini・4本)

架空の例(主語のない「ある会社では」型)の直後に「当社では…」が続く並びがある4本。AI が当社の支援の例と読むおそれがある(Perplexity の誤引用の原因)。E33 は 2026-10-18 に修正済み、ほかの3本は 2027-01-01 以降に修正。回答に社名(mentioned_v2 の表記)が出た件数を出す。**組ごとの比較はしない(判定には使わない)**

- E33 agentforce-sales-roleplay:0件 / 回答 2件
- E09 agentforce-mcp:0件 / 回答 2件
- E47 agentforce-proposal-review:0件 / 回答 1件
- E42 agentforce-sales-meeting:0件 / 回答 2件
- 計 0件
