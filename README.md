# crosscom-llmo-dashboard

cross-com.jp の **LLMO(LLM最適化)対策の成果を日次で観測する**データパイプライン。
KGI(指名検索・AI経由流入)と KPI(AI内での推薦のされ方・語られ方の質)の2階層を、
GitHub Actions による毎朝の自動収集 → Google Sheets 蓄積 → Looker Studio 可視化で運用する。

Brand Radar(Ahrefs)は Lite プランで利用不可のため、**LLM API 定点観測スクリプトで代替**している。
これが本システムの核である。

---

## アーキテクチャ

```
                         ┌──────────────────────────────────────────────┐
                         │            GitHub Actions (cron)             │
                         │                                              │
  daily.yml 07:00 JST ──▶│  run_daily.py                                │
  (cron: 0 22 * * * UTC) │   ├─ collect_llm.py  ── 7 prompts × 2 models │
                         │   │      │  (Gemini / Claude, 既定)          │
                         │   │      └─▶ data/raw/YYYY-MM-DD/*.json ──┐   │
                         │   ├─ extract.py (Anthropic Haiku) ◀───────┘   │
                         │   │      └─▶ 構造化(§4スキーマ)             │
                         │   ├─ analyze_sov.py  ── 競合SoV集計(Phase1) │
                         │   ├─ analyze_diff.py ── 前回観測との差分     │
                         │   ├─ collect_ga4.py ── AI経由流入(前日)     │
                         │   ├─ collect_gsc.py ── 指名検索(3日前)      │
                         │   ├─ sheets_writer.py ─▶ Google Sheets       │
                         │   └─ notify_slack.py ─▶ Slack Webhook       │
                         │                                              │
 backfill_sov.yml 手動 ──▶│  backfill_sov.py ─▶ sov_daily 全期間再生成   │
                         │                                              │
 weekly.yml 月08:30 JST ─▶│  run_weekly.py                               │
 (cron: 30 23 * * 0 UTC)│   ├─ collect_ahrefs.py ─▶ tab4 (best-effort) │
                         │   ├─ rules_engine.py ── 機械判定(第1段階)   │
                         │   │      └─▶ stats.json(統計+発火ルール)    │
                         │   ├─ generate_insight.py (Claude Sonnet)     │
                         │   │      └─▶ 所見文(第2段階・失敗時は数値のみ)│
                         │   └─ notify_slack.py ─▶ 週次所見をSlackへ   │
                         └───────────────────────────┬──────────────────┘
                                                     │
                              ┌──────────────────────▼───────────────────┐
                              │           Google Sheets(8タブ)          │
                              │  llm_observations / ga4_ai_traffic /     │
                              │  gsc_branded / ahrefs_aio / daily_summary│
                              │  sov_daily / changes        (Phase 1)    │
                              │  weekly_reports             (Phase 2)    │
                              └──────────────────────┬───────────────────┘
                                                     │
                     ┌───────────────────────────────▼──────────────────────────┐
                     │                    Looker Studio                          │
                     │  Sheetsコネクタ: llm_observations(KPI) / daily_summary   │
                     │  GA4ネイティブコネクタ / GSCネイティブコネクタ(KGI補完)  │
                     └───────────────────────────────────────────────────────────┘
```

### 2階層のKGI / KPI

| 階層 | 指標 | データ源 | タブ |
|------|------|----------|------|
| KGI | AI経由流入・CV | GA4 | `ga4_ai_traffic`, `daily_summary.ai_sessions` |
| KGI | 指名検索 | GSC | `gsc_branded`, `daily_summary.branded_clicks` |
| KPI | 推薦のされ方(言及率・順位) | LLM定点観測 | `llm_observations`, `daily_summary.mention_rate_*` |
| KPI | 語られ方の質(KBF/ネガ) | LLM定点観測 | `llm_observations`, `daily_summary.negative_flag_count` |
| KPI | 競合とのShare of Voice | LLM定点観測 | `sov_daily` |
| KPI | 前回観測からの変化 | LLM定点観測 | `changes` |
| 運用 | 週次の状態判定と推奨アクション | 上記すべて | `weekly_reports` |

---

## リポジトリ構成

```
crosscom-llmo-dashboard/
├── .github/workflows/
│   ├── daily.yml          # 毎朝07:00 JST(cron: '0 22 * * *' UTC)
│   ├── weekly.yml         # 毎週月曜08:30 JST(cron: '30 23 * * 0' UTC)
│   ├── monthly.yml        # 毎月第1火曜07:30 JST(Phase 3)
│   └── backfill_sov.yml   # sov_daily 全期間再生成(手動実行)
├── config/
│   ├── prompts.yaml       # 観測プロンプト定義(承認済み・変更禁止)
│   ├── prompts_monthly.yaml # 月次観測プロンプト M-1〜M-16(Phase 3・xlsx原文)
│   ├── entity_aliases.yaml  # 企業名エイリアス(運用中に追記する)
│   ├── entity_stoplist.yaml # 企業名でない一般名詞の除外リスト
│   ├── playbook.md          # 運用プレイブック(Phase 2・所見生成の根拠)
│   ├── rules_thresholds.yaml # ルール閾値(Phase 2・コード変更なしで調整)
│   ├── legacy_paths.yaml    # 旧事業URLパス(Phase 2 R-P8)
│   └── verdict_templates.yaml # 判定欄の文面(Phase 5・LLMを使わない)
├── src/
│   ├── collect_llm.py     # 4モデルへの定点観測クエリ実行
│   ├── extract.py         # 回答テキストからの構造化抽出
│   ├── normalize.py       # 企業名の正規化(Phase 1 §2-1)
│   ├── analyze_sov.py     # 競合Share of Voice集計(Phase 1)
│   ├── analyze_diff.py    # 前回観測との差分検出(Phase 1)
│   ├── notify_slack.py    # Slackアラート(Phase 1)
│   ├── backfill_sov.py    # sov_daily の全期間再生成(Phase 1)
│   ├── reextract_negative.py # 判定基準変更に伴うネガ行の再抽出(2026-08-24)
│   ├── rules_engine.py    # 週次の機械判定(Phase 2 第1段階)
│   ├── generate_insight.py # 週次所見の文章化(Phase 2 第2段階)
│   ├── insight_style.py   # 所見の記述ルール(Phase 7・表記/禁止語/統合)
│   ├── verdicts.py        # 判定欄の決定的生成(Phase 5)
│   ├── action_log.py      # 施策記録・提案の重複防止(Phase 5 / Phase 7 §A)
│   ├── citation_gap.py    # 引用元ドメインの3分類(Phase 5)
│   ├── board_daily.py     # Looker用フラットタブ(Phase 5)
│   ├── collect_ga4.py     # GA4:AI経由流入・CV
│   ├── collect_gsc.py     # GSC:指名検索
│   ├── collect_ahrefs.py  # 週次:AI Overviews引用KW(失敗時スキップ可)
│   ├── sheets_writer.py   # Sheets追記の共通処理(冪等upsert)
│   ├── settings.py        # 環境変数・定数・モデル有効/無効
│   ├── run_daily.py       # 日次オーケストレータ
│   ├── run_weekly.py      # 週次オーケストレータ
│   ├── run_monthly.py     # 月次オーケストレータ(Phase 3)
│   ├── kbf_compare.py     # 比較型のKBF別集計(Phase 3・lk_kbf_compare)
│   └── retired_urls.py    # 取り下げURLの引用ラグ測定(A-011)
├── app/                   # ローカル分析アプリ(Phase 4・Streamlit・読み取り専用)
│   ├── main.py            # エントリポイント(5ページのナビゲーション)
│   ├── data_source.py     # Sheets/ローカルの読み取りとキャッシュ
│   ├── common.py          # 共通ヘルパー(パース・チャート配色)
│   ├── board.py           # 8面共通の部品(カード・判定欄・注釈)
│   ├── sample_data.py     # 認証なしでUIを確認するためのサンプル
│   ├── faces/             # R1〜R8 の8面
│   └── views/             # 詳細3面(プロンプト・回答差分・週次所見)
├── credentials/           # サービスアカウントJSON(.gitignore・手動配置)
├── tests/                 # pytest(正規化・SoV・差分・Slack・backfill・週次ルール)
├── data/raw/              # LLM回答全文の保存先(git管理、日付ディレクトリ)
├── data/reports/          # 週次 stats.json / 再抽出レポート(git管理・監査用)
├── requirements.txt          # 実行系(GitHub Actions)
├── requirements-dashboard.txt # ローカル分析アプリ(Phase 4)
├── setup_dashboard.bat       # アプリ初回セットアップ(Windows)
├── run_dashboard.bat         # アプリ起動(git pull → streamlit)
└── README.md
```

---

## モデル構成(初期状態)

| モデルキー | 初期状態 | API | 既定モデル |
|-----------|---------|-----|-----------|
| gemini | 有効 | Gemini API + Google Search Grounding | `gemini-2.5-flash` |
| claude | 有効 | Anthropic Messages API + Web Search | `claude-sonnet-5` |
| chatgpt | **無効** | OpenAI Responses API + `web_search` | `gpt-4o` |
| perplexity | **無効** | Perplexity API | `sonar` |

- 日次観測 = 7プロンプト × 有効2モデル(gemini / claude)= **14クエリ**。
- 有効/無効は `settings.py`(環境変数 `ENABLE_CHATGPT` / `ENABLE_GEMINI` / `ENABLE_CLAUDE` / `ENABLE_PERPLEXITY`)で切替。
- **chatgpt / Perplexity 有効化は「キー登録 + `ENABLE_CHATGPT=true` / `ENABLE_PERPLEXITY=true`」のみでコード変更不要**。`OPENAI_API_KEY` / `PERPLEXITY_API_KEY` 未設定でもパイプラインはエラーにならない。
- モデル名は `OPENAI_MODEL` / `GEMINI_MODEL` / `ANTHROPIC_MODEL` / `EXTRACT_MODEL` で上書き可能。

### 収集の再試行と掃き直し

観測が取れなかった日は、その prompt_id × model が丸ごと欠測になる。
言及率も順位も母数から外れるので、欠測は「言及が無かった」ではなく
「分からなかった」であり、放っておくと週次の比較が静かに歪む。

| 設定 | 既定 | 役割 |
|---|---|---|
| `MAX_RETRIES` | 4 | 1観測あたりの試行回数 |
| `BACKOFF_BASE_SECONDS` | 5 | 待機の基準(5→10→20秒。合計35秒) |
| `RETRY_DELAY_CAP_SECONDS` | 90 | provider が指定した待ち時間の上限 |
| `SWEEP_COOLDOWN_SECONDS` | 60 | 一巡後、掃き直しに入るまでの待ち |

動きは4段階:

1. **provider の指示を優先する。** gemini の 429 は `RetryInfo.retryDelay`(例 14秒)を
   返す。固定のバックオフより長ければそちらを待つ。
2. **待っても直らないエラーは1回で止める。** `insufficient_quota`・401・403 など。
   待つだけ無駄で、しかもリクエスト枠を消費する。
3. **1日あたりの枠の 429 は、そのモデルのリトライを実行中は止める。**
   基本の1回は投げる(枠が数十秒で戻ることがあるため)。
4. **一巡したあと、失敗した観測だけを60秒待って1回だけ取り直す**(掃き直し)。

> **なぜ回数を増やさず待ち時間を増やすのか。**
> gemini の 429 が返す quotaId は `GenerateRequestsPerDayPerProjectPerModel-FreeTier`、
> quotaValue は **20 = 1日あたりのリクエスト数**。7プロンプト × 5回 = 35 では、
> 再試行そのものが枠を食い潰して欠測を増やす。回数は4回に抑え、
> 1回あたりの待ちを長くして障害窓をまたぐ。

> **2026-08 までの状態。** 待機は 2+4=6秒 しかなく、実測した障害窓(20〜90秒)の
> 中で3回とも落ちていた。直近7日で gemini が6件欠測(B-1×1・B-2×3・B-3×2)。
> さらに `collect_llm.collect()` が各レコードのエラーを内部で握って正常に返すため、
> `run_daily` の `_run` が `failures` に積まず、**日次Slackに欠測が出ていなかった**。
> 現在は `missing_observations()` の結果を `failures` に積むので、
> 欠測のある日は「❌ パイプライン一部失敗」に出る。

---

## Secrets 一覧(GitHub Actions Secrets に登録)

| Secret | 必須 | 用途 |
|--------|------|------|
| `GEMINI_API_KEY` | ○ | Gemini 定点観測 |
| `ANTHROPIC_API_KEY` | ○ | Claude 定点観測 + `extract.py` 構造化抽出 + 週次所見生成 |
| `OPENAI_API_KEY` | – | ChatGPT(有効化時のみ) |
| `PERPLEXITY_API_KEY` | – | Perplexity(有効化時のみ) |
| `GCP_SERVICE_ACCOUNT_JSON` | ○ | サービスアカウントJSON(Sheets / GA4 / GSC 共通) |
| `SHEETS_SPREADSHEET_ID` | ○ | 出力先スプレッドシートID |
| `GA4_PROPERTY_ID` | ○ | GA4 プロパティID(数値) |
| `GSC_SITE_URL` | ○ | 例 `sc-domain:cross-com.jp` または `https://cross-com.jp/` |
| `AHREFS_API_KEY` | – | 週次 Ahrefs(ベストエフォート) |
| `SLACK_WEBHOOK_URL` | – | Slackアラート・週次所見(未設定なら警告ログのみでスキップ) |
| `LOOKER_STUDIO_URL` | – | 日次アラート末尾のリンク(Secretではなく Variables でよい。未設定なら省略) |

### サービスアカウントの権限付与

`GCP_SERVICE_ACCOUNT_JSON` のサービスアカウントに以下を付与:

1. **Google Sheets** — 対象スプレッドシートをサービスアカウントのメールアドレスに「編集者」で共有。
2. **GA4** — 対象プロパティにサービスアカウントを「閲覧者」で追加(Data API 有効化)。
3. **GSC** — Search Console のプロパティにサービスアカウントを「制限付き」ユーザーとして追加(Search Console API 有効化)。

必要な OAuth スコープ(コード側で指定済み):
`spreadsheets` / `analytics.readonly` / `webmasters.readonly`。

### ローカル実行

```bash
pip install -r requirements.txt
export GCP_SERVICE_ACCOUNT_JSON="$(cat service_account.json)"   # or GOOGLE_APPLICATION_CREDENTIALS=path
export GEMINI_API_KEY=... ANTHROPIC_API_KEY=...                 # OPENAI_API_KEY は任意(chatgpt無効のため)
export SHEETS_SPREADSHEET_ID=... GA4_PROPERTY_ID=... GSC_SITE_URL=sc-domain:cross-com.jp
export SLACK_WEBHOOK_URL=...                                    # 任意(未設定ならアラートはスキップ)
cd src && python run_daily.py            # 日次
cd src && python run_weekly.py           # 週次(Ahrefs + 週次所見)
cd src && python run_weekly.py --skip-ahrefs --no-slack   # 所見だけ手元で確認
```

---

## Google Sheets スキーマ(承認済み・変更禁止)

| タブ | 粒度 | 主なカラム |
|------|------|-----------|
| `llm_observations` | 1日×1プロンプト×1モデル | date, prompt_id, pillar, model, mention, mention_type, rank, kbf_tags, negative_or_outdated, negative_detail, cited_crosscom_urls, competitors_mentioned, raw_file |
| `ga4_ai_traffic` | 1日×source×LP | date, source, landing_page, sessions, key_events |
| `gsc_branded` | 1日×query | date, query, clicks, impressions |
| `ahrefs_aio`(週次) | 1週 | date, aio_keyword_count, keywords_json |
| `daily_summary` | 1日 | date, mention_rate_all, mention_rate_pillar_a, mention_rate_pillar_b, negative_flag_count, ai_sessions, branded_clicks |
| `sov_daily`(Phase 1) | 1日×pillar×企業 | date, pillar, entity, mention_count, observed_total |
| `changes`(Phase 1) | 変化1件 | date, prompt_id, model, change_type, before, after, detail |
| `weekly_reports`(Phase 2) | 1週 | date, stats_json, report_md |
| `action_log`(Phase 5) | 施策1件 | action_id, 優先度, 内容, 対象, 根拠rule_id, 状態, 提案日, 実施日, 判断期限 |
| `citation_gap`(Phase 5) | 1週×ドメイン | date, domain, category, cited_count, prompts |
| `board_daily`(Phase 5) | 1日 | date, mention_rate_all_7d, …, noise_flag, material_events |

- **mention_rate** は当日の**有効観測数**(E-1を除く6プロンプト × 有効モデル数。初期は gemini / claude の2モデルで12観測)に対する `mention=true` 比率。有効モデル数に連動し、固定値はハードコードしない(モデルを増減すれば分母も自動追随)。
- **冪等性**:同一 `date × prompt_id × model` の行が既に存在する場合は上書き(同日再実行安全)。各タブとも主キーで upsert する。
- 抽出/観測に失敗した行も欠損として書き込み(`negative_detail` に `[error] ...` を記録)、`daily_summary` の分母からは除外する。

> 補足:`daily_summary.ai_sessions` は GA4(前日分)、`branded_clicks` は GSC(3日前分)の当日収集値を集計。
> LLM観測日(当日)を主キーとしたスナップショット行のため、各源の対象日付にはデータ確定遅延分のズレがある。

---

## 判定基準の変更履歴

指標の時系列を読むときは、**基準そのものが変わった日**を必ず確認する。
基準変更をまたいだ数値の増減は、実態の変化ではなく定義の変化であることがある。

### 2026-08-24 — `negative_or_outdated` を事業3区分ベースに精緻化

**変更前の問題**
`extract.py` の判定ルールが、MA・マーケティングオートメーション・メールマーケティング・
メール配信支援を**無条件に「旧事業」**として列挙していた。さらに
「現在の主要事業は Agentforce導入・定着支援と Agentic CRM設計支援**であり**」と
排他的に書かれていたため、それ以外の現行事業を現在形で語る回答まで TRUE になった。
**実際には提供している事業を「古い情報」と検知していた**(過剰検知)。

**確定した事業3区分**(2026-08-24・本田さん)

| 区分 | 事業 | ページの時制 | LLMO/SEO投資 | 現在形で語られたら |
|---|---|---|---|---|
| **注力事業** | Agentforce導入・定着支援 / Agentic CRM設計支援 | 現在形 | する | 正常 |
| **現行・非注力事業** | BtoB Salesforce導入・構築支援 / BtoB MA導入・構築支援 / メールマーケティング支援(受動対応) | 現在形を維持 | しない | **正常** |
| **終了事業** | BtoB マーケティング戦略コンサルティング支援 / MA・メール配信の「代行・運用」 | 過去形 | しない | **ネガ** |

分かれ目は語ではなく**形態**。「導入・構築」なら現行、「代行・運用」なら終了。
`MAの導入・構築を支援している` は正常、`MAの運用を代行している` はネガ。

**変更したもの**

- `src/extract.py` — `_build_prompt()` の `negative_or_outdated` 判定ルール、
  および `_SCHEMA_BLOCK` の `negative_detail` コメント。
  **JSONスキーマ・`mention_type` enum・`kbf_tags` 選択肢は変更していない**(§4承認済みのため)。
- `tests/test_extract_prompt.py` — 3区分と「導入・構築/代行・運用」の分かれ目を固定する
  テストを追加(APIを呼ばない)。
- `tests/manual_extract_negative_check.py` — 実APIでの確認ケースを8件→**10件**に拡張
  (`MAの導入・構築を支援=false` / `MAの運用を代行=true` を追加)。

**過去データの扱い**
今回の変更は「TRUE になる範囲を狭める」方向のみで、FALSE が新たに TRUE になることはない。
そのため**既に TRUE の行だけ**を `src/reextract_negative.py` で再抽出する。
書き戻すのは `negative_or_outdated` と `negative_detail` の2列だけで、
`mention` / `rank` / `kbf_tags` は再抽出結果で上書きしない
(抽出は決定的でないため、基準変更による差分とモデルの揺らぎが混ざるのを避ける)。
実行結果は `data/reports/reextract_negative_<実行日>.json` に残る。

```powershell
# 対象の確認だけ(APIも書き込みも無し)
.\.venv\Scripts\python.exe src\reextract_negative.py --dry-run

# 再抽出して書き戻す
$env:ANTHROPIC_API_KEY = "..."
$env:SHEETS_SPREADSHEET_ID = (Get-Content credentials\spreadsheet_id.txt)
$env:GOOGLE_APPLICATION_CREDENTIALS = "credentials\service_account.json"
.\.venv\Scripts\python.exe src\reextract_negative.py

# 書き戻しだけが失敗したときの再開(APIを再消費しない)
.\.venv\Scripts\python.exe src\reextract_negative.py `
  --from-report data\reports\reextract_negative_2026-08-24.json
```

> ⚠️ **ローカルの `credentials/service_account.json` はシートに対して読み取り専用。**
> 2026-08-24 の再抽出では書き戻しが `APIError: [403] The caller does not have permission`
> で失敗した。読み取り(658行)は成功しているので、原因はスコープではなく
> **スプレッドシートの共有権限**(`llmo-collector@crosscom-llmo.iam.gserviceaccount.com`
> が閲覧者になっている)。ローカルから書き戻す場合は、このアドレスを**編集者**に変更する。
> 再抽出の結果はレポートJSONに残るので、権限を直したあと `--from-report` で再開できる。

### 2026-08-24 の実行結果

| | 件数 |
|---|---|
| 再判定の対象(実行前 TRUE) | 17 |
| 再抽出成功 | 17 |
| **TRUE → FALSE(過剰検知だったもの)** | **1**(2026-08-24 A-1/gemini) |
| TRUE のまま(実態としてネガ) | 16 |
| 失敗 | 0 |

発火日数は 9日 → 9日で変わらず、合計件数のみ 17 → 16。
**8/18以降の毎日発火は過剰検知ではなく実態だった。**
E-1(エンティティ質問)の回答が、終了事業である「BtoB マーケティング戦略コンサルティング支援」
「MA導入・**運用**支援」「メールマーケティング**代行**支援」を現在の主要事業として
現在形で列挙し続けていることが原因。**P-7 の最優先対応は継続する。**

**読み方の注意**

- `daily_summary.negative_flag_count` と P-7 のネガ検知は、**8/24 の前後で定義が違う**。
  8/24 より前の値は、再抽出した行については新基準、それ以外は旧基準のままである。
- `config/legacy_paths.yaml`(P-8)にも同じ3区分の混同があった。**同日に是正済み**
  (下の「2026-08-24 — `legacy_paths.yaml` から現行事業のパスを除外」を参照)。
- `/btob-crm/` は 2026-08-24 時点で **404(実在しない)**。AIが存在しないURLを引用していた
  ハルシネーションだが、検知は継続するため定義からは削除していない。

### 2026-08-24 — `legacy_paths.yaml` から現行事業のパスを除外

`negative_or_outdated` と同じ混同が R-P8(旧事業URLの引用)の定義にも残っていたため、
**終了事業のパスだけを残す**よう是正した。

| パス | 対応する事業 | 判定 | E-1での引用回数(全期間) |
|---|---|---|---|
| `/btob-marketing-strategy/` | BtoB マーケティング戦略コンサルティング支援 | **終了 → 残す** | 7 |
| `/btob-crm/` | 実在しない(404・ハルシネーション) | **残す**(検知継続) | 4 |
| `/marketing-automation-btob/` | BtoB MA導入・構築支援 | 現行 → **除外** | 3 |
| `/ma-tool/` | 同上 | 現行 → **除外** | 0 |
| `/mail-magazine/` | メールマーケティング支援(受動対応) | 現行 → **除外** | 0 |

**影響**(観測済みの E-1 94行で実測)

- R-P8 の発火日数: **7日 → 7日(変化なし)**
- 根拠として挙がるURL: 14本 → **11本**(`/marketing-automation-btob/` の3本が外れる)

`negative_or_outdated` の再抽出と同じ結論で、これは**精度の修正であって件数の修正ではない**。
R-P8 が発火している日は、いずれも終了事業パス(`/btob-marketing-strategy/` `/btob-crm/`)が
実際に引用されている。**対応の必要性は下がっていない。**

除外したパスは削除ではなく、**理由つきのコメントとして yaml 内に残している**(再追加の防止)。
これらのページで「代行・運用」を現在形で訴求する記述が見つかった場合は、
パスを戻すのではなく**ページ側の文言を直す**。パスは事業区分の定義であって、
個別ページの文言の良し悪しを表すものではない。

### 2026-09-01 — 取り下げたURLの引用を日次で数え始めた(A-011)

PR TIMES の旧事業リリース2本を削除した(A-011)。ページを消しても、
モデルのインデックスやグラウンディングは古い参照をしばらく持ち続ける。
**その「しばらく」が何日かを実測する。**分かっていないと、次に掲載を
直したときに「直したのに所見が変わらない」の原因を、参照面のラグなのか
直しが足りないのかに切り分けられない。

- 定義: `config/retired_urls.yaml`。`status: deleted`(404)と
  `status: replaced`(URLは存置・中身を差し替え)を区別する
- 集計: `src/retired_urls.py`。日次で E-1 の引用と突き合わせる
- 記録: `lk_events` に「削除済みURLの引用」として**毎日1行**(0件の日も出す)

> **引用URLの全量は生データにしかない。** シートの `cited_crosscom_urls` は
> 自社ドメインだけを残す列なので、prtimes.jp のような外部ドメインは
> 構造上1件も入らない。そこを見ると常に0件になり「即日入れ替わった」と
> 誤読するため、`data/raw` の `cited_urls` を読む(citation_gap と同じ理由)。

> **gemini の引用の約6割は grounding のリダイレクト。** 実URLに解決しないと
> 中身が見えない。日次で解決してから数え、解決できなかった件数は
> `unresolved` として同じ行に残す。見えない分を黙って0に含めない。

### 2026-09-01 — `/email-marketing-support-company/` を legacy_paths に追加

E-1 引用元の共起監査(`output/reports/cooccurrence_audit_2026-09-01.md`)で、
**引用されているのに存在しないページ**が見つかった。

| 項目 | 内容 |
|---|---|
| パス | `/email-marketing-support-company/` |
| 現在 | HTTP 404(削除済み) |
| 削除前 | 2026-06-09 時点で 200。タイトルは「【2026年最新】メールマーケティング**運用代行**支援に強い企業11選」 |
| 引用 | 2026-07-08〜08-31 の E-1 で6回(すべて gemini のグラウンディング経由) |

**スラッグの字面と実際の区分が食い違う例。** `support-company` は
【現行・非注力】のメールマーケティング支援に読めるが、中身は「運用代行」で
【終了事業】にあたる。**パスの字面ではなく削除前の実際の記述で区分すること。**
判断には Wayback Machine を使った。

**ページを消しても検知は必要。** 削除しても gemini のグラウンディングは引用を
続けており、AIの回答には終了事業の情報が入り続ける。404 は解決ではないので、
`/btob-crm/` と同じ理由でパス定義に残す。

---

## Phase 1:SoV集計・差分検出・Slackアラート

日次パイプラインのフェーズ構成(既存踏襲で**1フェーズ失敗しても後続は実行**):

```
collect_llm → extract → analyze_sov → analyze_diff
→ collect_ga4 → collect_gsc → build_summary → Sheets書き込み → notify_slack
```

`analyze_diff` は**当日行を書き込む前**に走る。前回観測日を `llm_observations` から読むため、
先に当日行を書くと「当日 vs 当日」になってしまうからである。

### 1. `analyze_sov.py` — 競合Share of Voice(`sov_daily`)

- 各観測(prompt_id×model)の `competitors_mentioned` を展開し、`mention=TRUE` の観測では
  自社を「クロスコム」として1カウント加える。
- pillar `A` / `B` / `all` の3系列を出力(**E-1 は全系列から除外**。必ず自社に言及するため)。
- 1観測内の表記ゆれ(`DCS` と `三菱総研ＤＣＳ`)は正規化後に**1カウントに集約**する。
- `observed_total` に当日の該当pillar観測数を持たせ、シェア(= `mention_count / observed_total`)は
  Looker Studio / アプリ側で計算する。
- 自社行は言及ゼロの日も `mention_count = 0` で必ず出力する(自社SoVの時系列が途切れないため)。

### 2. 企業名の正規化 — `normalize.py` / `config/entity_aliases.yaml`

`normalize_entity()` は以下の順で処理する:

1. **NFKC正規化**(`三菱総研ＤＣＳ` → `三菱総研DCS`、`㈱` → `(株)`)
2. **括弧内の注記を除去**(`株式会社100（100inc）` → `株式会社100`)、**中黒の除去・空白の統一**
3. **法人格の除去**(前後から。`株式会社` / `合同会社` / `(株)` / `Inc.` / `Co.,Ltd.` / `LLC` 等)
4. **Latin↔CJK境界を含む空白の除去**(`EY ストラテジー…` = `EYストラテジー…`、
   `メンバーズ サースプラスカンパニー` = `メンバーズサースプラスカンパニー`。
   Latin語同士のスペースは可読性のため保持:`Deloitte Tohmatsu`)
5. **`config/entity_aliases.yaml` によるエイリアス統合**(大文字小文字**と空白**を無視)

```
「株式会社メンバーズ サースプラスカンパニー」→「メンバーズ」
「三菱総研ＤＣＳ」「ＤＣＳ」            →「三菱総研DCS」
「船井総研」                            →「船井総合研究所」
「株式会社100（100inc）」「100 Inc.」   →「ハンドレッド」
「Uhuru」「株式会社ウフル」             →「ウフル」
```

- **未知の企業名は正規化のみ適用してそのまま記録**する(取りこぼしを作らない)。
- 表記ゆれを見つけたら `entity_aliases.yaml` に追記するだけでよい(**コード変更不要**)。
  YAML側の値も同じ正規化を通してから照合するため、法人格・中黒・空白の付いた形を
  個別に列挙する必要はない。
- **同じキーを2回定義するとエラーで落ちる**。素のYAMLは後勝ちで上書きするため、
  既存キーの再定義に気付けず編集が黙って無効化される事故を防ぐ
  (`settings.load_yaml` / `DuplicateKeyError`。prompts / aliases / stoplist 共通)。
- **法人格を除いて数字だけになる場合は除去しない**。`株式会社100` を `100` に潰すと
  エイリアスに一致しなくなり、`sov_daily` に意味のない `100` 行が生まれるため
  (実際に発生した不具合)。
- エイリアス照合は**「文字を含まない値の除外」より先に**効く。したがって数字だけの
  表記でも、YAMLに登録すれば正規エンティティとして集計される
  (`100` →「ハンドレッド」)。逆に未登録の `2018` のような断片は除外される。

### 2-1. 一般名詞の除外 — `config/entity_stoplist.yaml`

LLMが競合として挙げたもののうち、企業名でない表現(`ブティック型DXコンサルティングファーム`
`大手SIer` `その他` など)を集計から落とす。**正規化の後**に適用する。

| セクション | 照合 | 使いどころ |
|---|---|---|
| `exact` | 完全一致 | 既定。誤爆がないので迷ったらこちら |
| `contains` | 部分一致 | 「その語を含む実在社名はない」と言い切れる語のみ |

- 大文字小文字と空白を無視して照合する(`大手 SIer` も `大手SIer` も除外)。
- コード側の追加ガードとして、**文字を1つも含まない値**(`100`、`2018`)も除外する。
- 集計に入る/入らないの判定は `resolve_entity()` に集約されており、`analyze_sov` と
  `analyze_diff` の両方が同じゲートを通る(差分側でも一般名詞の出入りがノイズにならない)。
- **除外は静かに効くため**、`backfill_sov.py` は除外された値とその件数を必ず出力する。
  そこに実在の競合が出てきたら、それは `entity_stoplist.yaml` ではなく
  `entity_aliases.yaml` に入れるべき値である。

### 3. `analyze_diff.py` — 前回観測との差分(`changes`)

`llm_observations` から**当日より前で最も新しい日**を取得し、prompt_id×model 単位で比較する。
**前回データがない初回実行は「差分なし」で正常終了**する。

| change_type | 条件 |
|-------------|------|
| `mention_gained` / `mention_lost` | mention の FALSE↔TRUE |
| `rank_up` / `rank_down` | rank変化(数値が小さい=上昇)。推薦リスト外は `圏外` として比較 |
| `competitor_added` / `competitor_removed` | **正規化後**の競合集合の差分(`detail` に企業名) |
| `crosscom_url_added` / `crosscom_url_removed` | `cited_crosscom_urls` の差分(`detail` にURL) |
| `negative_flag_on` / `negative_flag_off` | `negative_or_outdated` の変化 |

- 競合は正規化してから集合比較するため、**表記ゆれだけの変化はノイズとして出ない**。
- 抽出エラー行はどちらの日でも比較対象から除外する。
- 冪等キーは `date × prompt_id × model × change_type × detail`
  (同日に複数社が追加されても行が潰れず、再実行では上書きになる)。

### 4. `notify_slack.py` — Slackアラート

**「状態を示す通知 + 詳細はリンク先」**。日次は毎日1通、3階層で固定する。

```
📊 *LLMO日次* | 2026-08-18
言及率 *50%* ↑(+17%)  |  SoV首位 *クロスコム*  |  ネガ検知 *1件*

⚠️ E-1 × claude — 旧事業(MA/メール配信)の記述（継続5日目）
📈 言及獲得: B-1(gemini)
📉 言及消失: A-3(claude)
❌ パイプライン一部失敗: collect_ga4

<スプレッドシート>  |  <Looker Studio>
```

| 階層 | 内容 |
|---|---|
| 1行目 | `📊 LLMO日次 \| 日付` |
| 2行目 | 言及率(当日・前日比の矢印 ↑→↓) / SoV首位 / ネガ検知件数 |
| 3行目以降 | 変化イベントのみ1行ずつ。無ければ「変化なし」1行 |
| 末尾 | スプレッドシート / Looker Studio(`LOOKER_STUDIO_URL` 未設定なら省略) |

- **`negative_detail` の本文は載せない。** 毎日ほぼ同じ長文になり通知が読まれなくなるため、
  種別(20字以内)と**継続日数**だけを示す。本文はスプレッドシートで読む。
- 継続日数は `llm_observations` から同一 prompt_id の連続検知日数を数える
  (モデル単位ではなく prompt_id 単位。片方のモデルで出ていればその日は検知あり)。
- **変化がない日も送る。** 状態を毎日出さないと、無音の日と壊れた日を区別できない。
  ここで見たいのは発火そのものではなく**発火が止まった日**である。
- 言及率は `build_summary` と同じ定義(E-1とエラー行を除外)。
- **未設定でもパイプラインは落ちない**(警告ログとメッセージ本文を標準出力に出して正常終了)。
- Python到達前にワークフローが落ちた場合(checkout / pip install の失敗など)は、
  `daily.yml` 最終stepの `if: failure()` が Webhook へ直接POSTする。
- **週次所見(`notify_weekly`)は役割が違うため現行の長文フォーマットを維持**している。
  日次は毎日「状態」を読むもの、週次は週1回「深さ」を読むもの。

**テスト送信**:

```bash
cd src
SLACK_WEBHOOK_URL=... python notify_slack.py --test         # 変化イベントあり
SLACK_WEBHOOK_URL=... python notify_slack.py --test-quiet   # 変化ゼロの日
SLACK_WEBHOOK_URL=... python notify_slack.py --test-weekly  # 週次(現行フォーマット)
```

### 5. `backfill_sov.py` — sov_daily の全期間再生成

`sov_daily` は `llm_observations` から**完全に導出できる**(観測データを持たない)。
そのため正規化ルールを変えたら、タブを捨てて全日再生成するのが正しい直し方である。
エイリアスやストップリストを更新したら必ず実行する。

```bash
cd src
python backfill_sov.py --dry-run          # 書き込まず結果と除外内訳だけ表示
python backfill_sov.py                    # sov_daily を全期間置き換え
python backfill_sov.py --since 2026-08-01 # 範囲外の日はそのまま保持
```

GitHub Actions からも実行できる:**Actions → backfill-sov → Run workflow**
(`dry_run` は既定でON。中身を確認してからOFFで本実行する)。

- 通常の日次パイプラインは冪等upsert(`write_sov_daily`)のままで、こちらは
  **タブ置き換え**(`rewrite_sov_daily`)を使う。正規化変更で消えるべき行
  (古い `100` 行など)はupsertでは削除できないため。
- `changes` タブは再生成しない。過去の行には旧表記の競合名が残るが、変化イベントの
  記録としては当時の値のままが正しい。

### 6. テスト

```bash
pip install -r requirements.txt
python -m pytest tests -q        # リポジトリルートで実行
```

- `tests/test_normalize.py` — 全角/法人格/括弧注記/エイリアス統合、ストップリスト、
  未知企業の素通し、冪等性、`Marco` のような誤爆防止
- `tests/test_analyze_sov.py` — pillar別集計、E-1除外、1観測内の重複集約、`observed_total`
- `tests/test_analyze_diff.py` — 前回データなし、mention flip、rank変化、競合追加削除、URL/ネガ変化
- `tests/test_notify_slack.py` — セクション順序、ゼロ通知、Webhook未設定時の無害動作
- `tests/test_backfill_sov.py` — 全期間再生成、表記ゆれの統合、除外内訳、日付範囲
- `tests/test_settings_yaml.py` — 設定YAMLの重複キー検出
- `tests/test_rules_engine.py` — 全7ルールの 発火/非発火/データ不足(Phase 2)
- `tests/test_generate_insight.py` — プロンプト構成、数値禁止事項、フォールバック、Slack整形
- `tests/test_run_weekly.py` — 週次オーケストレーションの配線とLLM障害時の縮退

---

## Phase 2:AI所見エンジン(週次自動レポート)

蓄積データから「今週の状態判定と推奨アクション」を毎週自動生成し、Slackに配信する。
**週次レビューを「読んで承認するだけ」にすることが目的。**

### 設計の核 — 判定と文章化を分離する

```
第1段階(コード・決定的)      第2段階(Claude API)
rules_engine.py       ──▶   generate_insight.py
統計値とルール発火を機械判定    stats.jsonだけを材料に日本語化
= テスト可能               = 判定はしない・数値も作らない
```

**LLMに生データの解釈や判定をさせない。** モデルが見るのは stats.json と
プレイブックだけで、回答全文もスプレッドシートも渡らない。
「発火したかどうか」は必ず第1段階で決まっている。

### 1. `rules_engine.py` — 第1段階:機械判定

直近28日分の全タブを**タブごと1回**だけ読み、以下を算出する。

**週次統計(§2-1)**

| 項目 | 内容 |
|---|---|
| mention_rate 3系列 | 直近7日平均 vs 前週7日平均(差分付き)。`daily_summary` から算出しダッシュボードと一致させる |
| 言及マトリクス | prompt_id×model の 言及日数/観測日数(直近7日) |
| rank推移 | prompt_id×model の中央値、今週 vs 前週 |
| SoV上位10 | all/A/B別、前週比の増減付き |
| changes集計 | change_type別件数(直近7日) |
| KGI | AI経由セッション・指名クリック/インプレッションの週計 vs 前週 |

**発火ルール(§2-2)**

| rule_id | 発火条件 |
|---------|---------|
| `R-P2` | 過去に言及実績があり、直近3観測日連続で mention=FALSE(証跡には**実際の連続日数**と開始日を記録) |
| `R-P4` | pillar別 mention_rate 7日平均が前週比 +0.10 以上 |
| `R-P5` | prompt_id の rank中央値が 6以上(=順位が悪い)の週が4週連続 |
| `R-P7` | 直近7日に negative_or_outdated=TRUE が1件以上(detail同梱) |
| `R-P8` | E-1 の引用URLに旧事業パスが含まれる(`config/legacy_paths.yaml`)。下記の制約あり |
| `R-P15` | 自社不在の prompt_id で、同一競合が直近7日に両モデル出現かつ4週連続 |
| `R-DROP` | SoV上位5の競合が前週比で半減、または新規エンティティが上位5入り |

- 各ルールは **`fired` / `not_fired` / `insufficient_data`** の3状態を返す。
  **データ不足は発火扱いにしない**。判断できないことをレポートに明記するための状態である。
- 閾値はすべて `config/rules_thresholds.yaml`(コード変更なしで調整可能)。
- 競合判定では自社(クロスコム)を除外し、企業名は Phase 1 の `resolve_entity()` を通す。

**KGIのノイズガード**

現状の母数(週2セッション・週4クリック)では、週次の増減に意味がない。
今週の週計が `kgi.noise_floor`(既定10)未満の指標には **`noise_zone: true`** を立て、
所見生成プロンプト側で**「悪化」「改善」「要対応」と書くことと、推奨アクションの根拠に
使うことを禁止**している。実数は必ず併記されるので、変化自体は読み手に見える。

判定は**今週の値のみ**で行う(前週は見ない)。4クリックという水準は、前週が10でも20でも
打ち手を決められる母数ではないため。母数が育ったら `noise_floor` を引き上げる。

**判定できた範囲(`coverage`)**

一部のデータしか見られなかった `not_fired` は、「問題なし」より弱い主張である。
R-P8 は `coverage` に評価できた観測数とモデル名を記録し、プロンプト側でも
「一部しか評価できていない `not_fired` を問題なしと言い切らない」よう指示している。

> **既知の制約 — R-P8 は実質 claude のみで判定される。**
> Gemini は引用URLを `vertexaisearch.cloud.google.com/grounding-api-redirect/...` の
> 形で返すため、自社ドメインが文字列として現れず `cited_crosscom_urls` が常に空になる。
> §4の抽出仕様は変更禁止のため、リダイレクト解決は行わず**制約として可視化する**方針とした。
> E-1の観測が1件も自社URLを持たない週は `not_fired` ではなく `insufficient_data` を返す。

> **`R-P5` の向きについて**:`rank` は小さいほど良い。指示書の「6以下」は
> 併記された「(=6位以上悪い)」に従い **中央値 ≥ 6 で発火**として実装している。

### 2. `generate_insight.py` — 第2段階:所見文生成

- 入力は **stats.json のみ**。モデルは Sonnet クラス(`INSIGHT_MODEL` で上書き可)、**週1回だけ**呼ぶ。
- `config/playbook.md` をシステム指示に同梱し、発火した P-パターンの
  「原因仮説と改善策」をそこから書かせる。
- **stats.json にない数値・事実を書くことを明示的に禁止**している(推測値・概算も不可)。
- 出力は5セクション固定(サマリ / 数値ハイライト / 発火パターンと推奨アクション /
  ウォッチ項目 / 判定不能・データ不足)、2,000字以内。
  推奨アクションは**承認/却下できる粒度で最大3件**。

**LLMが落ちてもレポートはゼロにならない。** `fallback_report()` が同じ5セクションを
stats.json の数値だけで組み立て、配信を継続する(冒頭に自動生成失敗の断り書きが入る)。

#### 2-1. 実施済み施策の再提案を止める(Phase 7 §A)

推奨アクションを書かせる前に `action_log` を読み、状態が
**承認 / 実施済み・効果測定中 / 完了** の施策を「着手済みの施策」としてプロンプトに渡す。
同じ**根拠rule_id + 対象**の施策は新たに提案させない。

それでも本文に残った場合は `action_log.suppress_settled()` が後処理で差し替える。
行を消さずに `推奨アクション: 実施済み(A-001・2026-08-11)。効果測定中` の1行にするので、
その面に対して何をしたのかは所見の上で追える。
承認だけ済んでいて実施日が無い施策は `承認済み(A-010・2026-08-29)。着手前` と書く
(「実施済み」と書くと嘘になるため)。

#### 2-2. 記述ルール(Phase 7 §B) — `insight_style.py`

所見は毎週同じ読み方をされる。同じ状態なら同じ言い回しで出ることが前提なので、
判定欄(`verdicts.py`)と同じ考え方で、決められる部分は決めてしまう。
プロンプトで指示し、確定的に直せるものは `insight_style.py` が後処理で直す。

| ルール | 例 | 直し方 |
|---|---|---|
| 率は%、率の差分は「ポイント」 | `0.4818` → `48%` / `-0.0182` → `-2ポイント` | stats.json の値と1対1で対応する置換表を作って当てる。順位中央値のような率でない小数は触らない |
| 前週比が±5ポイント以内は「横ばい」 | `48%(前週50%、前週比 横ばい(-2ポイント))` | 閾値は `rules_thresholds.yaml` の `insight.flat_delta_points`。実数は括弧で必ず併記する |
| 発火パターンは初出時に日本語の説明を併記 | `R-P2(言及消失:同一プロンプトで3観測日以上言及がない)` | 説明文の数値は `rules_thresholds.yaml` から組み立てる(閾値を変えると説明も追従する) |
| 3行の箇条書き・矢印記法は使わない | `状態:` / `原因仮説:` / `推奨アクション:` | `状態→` を `状態:` に正規化。残った `→` は警告に積む |
| 各文に主語を明示 | 「AIの回答は」「クロスコムは」「競合の◯◯社は」 | プロンプトのみ(機械判定できない) |
| 禁止語(比喩) | 押し出す / 定着 / 供給 / 型 / 浮上 / 急落 / 様子見 | `insight_style.BANNED_WORDS`。**自社サービス名「Agentforce導入・定着支援」だけは例外** |
| 同一プロンプトの R-P2 と R-P15 は1項目に統合 | `**R-P2・R-P15 — B-3**` | 推奨アクションの順序は「①競合の引用ページ調査 → ②自社ページ更新」に固定 |

機械で直せなかったもの(残った比喩、主語の省略、セクションの欠落)は
**消さずに warnings に積み**、GitHub Actions のジョブサマリに出す。
黙って直すより、直っていないことが分かるほうがよい。

禁止語は「所見の語彙の出どころ」側で断つ:`config/playbook.md`、
`rules_engine.py` の `detail`、`fallback_report()` のいずれにも禁止語が無いことを
`tests/test_insight_style.py` が固定している(`tests/display_text.py` の英字検査と同じ方式)。

#### 2-3. 応答が途中で切れないようにする(Phase 7 §C)

`INSIGHT_MAX_TOKENS`(既定 16,000)で1回の応答の枠を決め、
`stop_reason == "max_tokens"` を検出したら `TruncatedResponse` を投げる。
`generate()` は一度だけ枠を倍にして呼び直し、それでも切れるならフォールバックに落とす。
加えて後処理が5セクションの欠落を検出して警告に積む。

> **2026-08 までの欠陥。** `max_tokens=4096` 固定で `stop_reason` を見ておらず、
> text ブロックを連結してそのまま配信していた。結果として
> 8/17・8/24・8/31 の3週とも所見が文の途中で切れ、
> セクション4(ウォッチ項目)・5(判定不能・データ不足)が丸ごと欠落していた。
> Slack の投稿上限(38,000字)には遠く届いておらず(本文は962〜1,531字)、
> シート書き込み側にも切り詰めは無いため、原因は生成側だけである。

### 3. `config/playbook.md` — 所見の根拠

`generate_insight.py` が「原因仮説」と「改善策」を書く際の**唯一の根拠**。
P-2 / P-4 / P-5 / P-7 / P-8 / P-15 / P-DROP それぞれについて
**状態・原因仮説・改善アクション** を定義している。

> ⚠️ **現在のファイルは草案である。** 実装時点でリポジトリ内に運用プレイブックの
> 現物がなかったため、指示書のルール定義と既存の観測プロンプト・KBFから再構成した。
> 判定ロジックは指示書どおりなので動作に影響はないが、**所見文の質は
> このファイルの正確さに直結する。実際の運用方針と照らして必ずレビューすること。**
> 修正はMarkdownを編集するだけでよい(コード変更不要)。

### 4. 配信と保存

- **Slack**:毎週月曜 08:30 JST に既存Webhookへ1投稿。冒頭は `LLMO週次所見 YYYY-MM-DD`。
  Markdown は Slack mrkdwn に変換して送る(見出し・太字)。
- **Sheets**:`weekly_reports` タブに `date / stats_json / report_md` を冪等upsert。
  stats_json がセル上限(50,000字)に近い場合は要約に切り替え、全文は下記ファイルを参照する。
- **Git**:`data/reports/YYYY-MM-DD.json` として commit(監査用)。

### 5. 実行

```bash
# 定期実行:毎週月曜 08:30 JST(cron: '30 23 * * 0' UTC)
# 手動実行:Actions → weekly → Run workflow(date / skip_ahrefs を指定可)

cd src
python run_weekly.py --date 2026-08-17              # 通常
python run_weekly.py --skip-ahrefs --no-slack       # 所見だけ手元で確認(投稿しない)
python rules_engine.py --date 2026-08-17 --out /tmp/stats.json
python generate_insight.py --stats /tmp/stats.json --fallback-only   # LLMを使わず整形だけ確認
python generate_insight.py --stats /tmp/stats.json --action-log /tmp/actions.json  # 施策記録を手元のJSONで差し替えて生成
python notify_slack.py --test-weekly --date 2026-08-17               # 週次投稿のテスト送信
```

**終了コードの約束**:Ahrefs の失敗は best-effort なので緑のまま。
それ以外の失敗(所見のフォールバック使用を含む)は**赤にする** —
数値だけのレポートが届いたことに気付けるようにするため。

---

## Phase 3:月次観測(BOFU・購買直前面)

### なぜ足したか

日次観測7本は **MOFU(検討段階)** 中心で、**BOFU(購買直前:社名指名・競合比較)**
の面が空白だった。「Agentforce導入支援の会社を教えて」は観測できていたが、
「クロスコムの評判は」「クロスコムとテクノデジタルコンサルティングを比較して」は
一度も観測していなかった。**買う直前にAIが何と答えるか**を月次で12本測る。

### 実行数の制約(設計の中心)

Gemini 無料枠は `GenerateRequestsPerDayPerProjectPerModel-FreeTier` で
**1日20リクエスト/モデル**。月次は日次と同じ日に走るので合計で見る必要がある。

```
日次 7本 + 月次 12本 = 19 / 20
```

**active な月次プロンプトを13本以上にすると枠を超える。**
増やす場合は実行を2日に分割する設計に変えること。
この上限は `tests/test_monthly.py::test_the_monthly_run_fits_in_the_gemini_daily_quota`
が検査していて、超えると CI が落ちる。

### 構成

| ファイル | 役割 |
|---|---|
| `config/prompts_monthly.yaml` | M-1〜M-16。**M-1〜M-12 が active、M-13〜M-16 は第2弾候補で active: false** |
| `src/run_monthly.py` | オーケストレータ。収集 → 抽出 → シート → Slack |
| `.github/workflows/monthly.yml` | 毎月第1火曜 07:30 JST + workflow_dispatch |
| `monthly_observations`(タブ) | `llm_observations` + `category` / `target_brand` / `notes` |
| `data/raw/monthly/YYYY-MM-DD/` | 回答全文 |

**日次・週次には一切混ぜない。** `monthly_observations` は別タブで、
`daily_summary` にも `read_for_rules()` にも入らない。混ぜると言及率・言及シェアの
母数が月に一度だけ跳ね、日次指標の時系列が読めなくなる。
`tests/test_monthly.py` がこの分離を固定している。

収集は `collect_llm.collect(date, prompts=..., out_dir=...)` を使い回す。
リトライ・掃き直し・欠測通知を月次側に書き写すと、片方だけ直るバグの温床になる。

### プロンプトの区分(LANYフレームとの対応)

| category | 本数 | 内容 |
|---|---:|---|
| `bofu_single` | 6 | 社名指名。評判・費用・実績・専門性をAIが何と答えるか |
| `bofu_compare` | 3 | 競合との直接比較。`target_brand` に相手を記録 |
| `mofu_suppl` | 3 | 日次で観測できていないMOFU(L0純粋形・業界軸・規模軸) |

**プロンプト全文は `クロスコム_月次観測プール設計_v1.xlsx` の
シート「月次観測プール_第1弾」から一字一句そのまま写している。**
文言を変えると前月との比較が成立しないため、`tests/test_monthly.py` が
16本すべての原文を持って照合している。

### 比較型の読み方

月次サマリは、比較型について機械で言えるところまでしか書かない。

- 自社に言及があるか / 競合が併記されているか / 順位
- 両社に言及があって順位が取れない場合は **「要目視」** と書く

どちらが良く書かれたかの判断はしない。抽出スキーマ(§4)は変更しておらず、
勝敗判定のような新項目は足していない。

**同名他社との混同は `negative` 扱いにしない。** `notes` 列に記録して
月次サマリで「📝」として報告する。エンティティの混同は情報の古さとは別の問題で、
混ぜると R-P7 の意味が壊れる。

### 比較型のKBF別集計(`lk_kbf_compare`)

比較3本(M-7〜M-9)は自然文なので、毎月人が読み直さずに済むよう
**KBFごとに「その軸を誰が語ったか」だけ**を機械で拾い、月をまたいで並べる。

| 列 | 内容 |
|---|---|
| `month` / `prompt_id` / `model` / `kbf` | 一意キー |
| `self_eval` / `rival_eval` | その軸が自社/競合の文脈で語られたか |
| `diff` | `self` / `rival` / `both` / `neither` |

**優劣は判定しない。**「どちらが優れているか」は回答文の含意で、機械では取れない。
取れないものを取れたことにすると月次サマリの「要目視」と矛盾する。
ここで出すのは**軸の占有**だけ。`diff: rival` が埋めるべき軸になる。

自社/競合の切り分けは、KBF語の**直前にある社名**で決める。比較回答は
「◯◯社は…」と社名で節が始まる構造のため。単純な近さで測ると、直後に
別の社名が来ただけでそちらの節に取られる。

### 第2弾の追加手順

1. `config/prompts_monthly.yaml` の該当プロンプトを `active: true` にする
2. `tests/test_monthly.py` の枠テストが落ちることを確認する(13本以上で落ちる)
3. 落ちるなら **実行を2日に分割する**(1日の枠を超えたまま動かさない)
4. `tests/test_monthly.py` の `test_the_first_wave_is_twelve_prompts` を更新する

### 実行

```bash
# 定期実行:毎月第1火曜 07:30 JST(cron: '30 22 * * 1' + JSTの日付でガード)
# 手動実行:Actions → monthly → Run workflow(date を指定可)

cd src
python run_monthly.py                          # 通常
python run_monthly.py --no-slack --no-sheets   # 手元で本文だけ確認
python notify_slack.py --test-monthly          # 月次サマリのテスト送信
```

---

## Phase 4:ローカル分析アプリ(Streamlit)

**日常の閲覧は Looker Studio。本アプリは回答差分の確認用**(Phase 6 §3)。
8面の指標・判定はすべて Looker 側に出るようになったので、ここを毎日開く必要はない。
残しているのは、回答全文の突き合わせと2日付の差分表示が Looker では組めないため。

**完全ローカル・読み取り専用**で、実行系(daily / weekly)には一切影響しない。

### セットアップ(2ステップ)

```
1. setup_dashboard.bat   ← venv作成 + 依存インストール(初回のみ)
2. run_dashboard.bat     ← git pull → アプリ起動(ブラウザが自動で開く)
```

**サービスアカウントJSONの配置**(Sheets系ページに必要):

| 置くもの | 場所 |
|---|---|
| サービスアカウントJSON | `credentials/service_account.json` |
| スプレッドシートID | `credentials/spreadsheet_id.txt`(1行)または環境変数 `SHEETS_SPREADSHEET_ID` |

`credentials/` は **.gitignore 済み**でコミットされない。日次パイプラインと同じ
サービスアカウントを使えばよい(読み取りのみ)。

### 画面構成

| ページ | 内容 | 認証 |
|---|---|---|
| **P1 概況** | mention_rate 3系列のスコアカード(7日平均+前週比)、SoV首位、negative_flag、KGI週計(ノイズ域は警告表示)。下段に全期間推移+7日移動平均 | 要 |
| **P2 SoV分析** | pillar/期間フィルタ、上位N社のシェア推移(クロスコムは赤で固定)、出現回数ランキング(前期間比) | 要 |
| **P3 プロンプト詳細** | prompt_id×model の mention/rank 推移(rank軸は反転)、kbf_tags頻度、競合集計、引用URL一覧 | 要 |
| **P4 回答ビューア・差分** | `data/raw` の回答全文、2日付のdiff(追加/削除ハイライト)、同日のchanges併記 | **不要** |
| **P5 週次所見** | weekly_reports の一覧とMarkdown本文、stats.json の主要数値(折りたたみ) | 要(stats.jsonはローカルで表示可) |

### 設計上の約束

- **読み取り専用**。`src/sheets_writer` を経由せず独自の読み取りクライアントを持つため、
  アプリから書き込み経路に到達できない。
- **APIクォータを圧迫しない**。タブごと1回読み + `st.cache_data`(TTL 10分)。
  サイドバーの「キャッシュを更新」で明示的に再取得できる。
- **認証がなくても落ちない**。Sheets系ページは何が足りないかを名指しで案内し、
  P4 は `data/raw` だけで通常どおり動作する。
- **依存は分離**。`requirements-dashboard.txt` にのみ streamlit / plotly / pandas を置き、
  実行系の `requirements.txt` には混ぜない。

### 表示文言は日本語(内部名は英字のまま)

画面に出る文言はすべて日本語にする。ただし **シートのタブ名・カラム名、
`action_id` / `rule_id` / `prompt_id` の値、yaml やコードの内部名は変更しない**。
日本語化は表示の直前だけで行い、対応表は `app/labels.py` に集約している。

| 内部名 | 画面表示 |
| --- | --- |
| SoV | 言及シェア |
| KGI | 成果指標(各画面の初出だけ「成果指標(KGI)」と併記) |
| Pillar A / Pillar B | Agentforce系(A) / Agentic CRM系(B) |
| mention / mention_rate | 言及 / 言及率 |
| rank / model / prompt_id | 順位 / モデル / プロンプト |
| TRUE / FALSE | あり / なし |
| fired / not_fired / insufficient_data | 発火 / 非発火 / 判定不能 |
| `action_log` の対象列の `KGI` | 成果指標(プロンプトIDは識別コードなのでそのまま) |

`app/labels.py` の使い分け:

- `ja_columns(frame)` — 表の見出しを表示直前に訳す(元のフレームは変えない)
- `column(name)` / `pillar(code)` / `status(value)` / `target(value)` /
  `yes_no(value)` — 値1つ分。対応表に無い値はそのまま返す
- `change_rows(rows)` — `changes` タブの `change_type` と真偽値を訳す

英字のまま残してよいのは次の5種だけ。許可語は `tests/display_text.py` の
`ALLOWED_WORDS` にあり、判定欄テンプレートの検査もこの同じリストを使う。

1. 製品・サービス名(Gemini / Claude / Salesforce / Agentforce / Looker Studio 等)
2. 識別コードの**値**(R1〜R8 / A-001 / R-P7 / A-1〜E-1)。見出しやラベルは日本語
3. 定着した略語(AI / KBF / CEP / URL)
4. ドメイン・URL
5. リポジトリ内部のファイル名・タブ名(バッククォートでコード表記した場合のみ)

`tests/test_app_labels.py` が `app/` 配下の表示位置の文字列リテラルを走査し、
許可語に無い英単語があれば落とす。走査するのは**表示位置**だけなので、
カラム名やタブ名を引数に渡すコードは検出対象外(変更禁止のため)。

週次所見の本文は生成物なので、語彙の指示は `src/generate_insight.py` の
プロンプトに入れてある。**すでに保存済みのレポートは書き換えていない**
(過去の記録なので、表示層の変更では触らない)。

### UIだけ先に確認したいとき(サンプルモード)

認証を用意する前に画面を確認できる。**全ページに警告バナーが出る**:

```
set LLMO_DASHBOARD_SAMPLE=1
.venv\Scripts\python.exe -m streamlit run app\main.py
```

起動後 http://localhost:8501 を開く(この起動方法ではブラウザは自動で開かない)。
合成データを表示するだけで、Google Sheets には一切接続しない。

### バッチファイルを編集するときの注意

`setup_dashboard.bat` / `run_dashboard.bat` は **ASCII のみ・CRLF 改行**で保存すること。

- cmd.exe はバッチをコンソールのコードページ(日本語Windowsでは CP932)で読むため、
  **UTF-8 の日本語を書くと文字化けし、解析が壊れる**。メッセージは英語で書く。
- **改行が LF だけだと cmd が誤解析する**(`'n' は、内部コマンド…` が大量に出る)。
  `.gitattributes` で `*.bat text eol=crlf` を固定しているので、
  チェックアウト時は自動的に CRLF になる。エディタ側の設定にも注意。
- `.streamlit/config.toml` で `headless = true` にしているのは、
  Streamlit の初回起動時メール入力プロンプトを抑止するため
  (プロンプトが出ると入力待ちで起動が止まる)。ブラウザは `run_dashboard.bat` が開く。

---

## Phase 5:8面レポート構成

数値の羅列ではなく「状態 → 原因 → アクション承認」の順で意思決定が終わる画面にする。

| 面 | 名称 | 中身 |
|----|------|------|
| R1 | 全体サマリ | 指標カード4枚 + 実施中の施策 |
| R2 | 言及率トレンド | 移動平均3系列 + 施策実施日の縦線 |
| R3 | ネガ検知 | モデル別の日次カレンダー + 施策基準線 |
| R4 | 獲得マップ | prompt×model の言及日数ヒートグリッド |
| R5 | 競合ポジション | 散布図(シェア×順位) + シェアランキング |
| R6 | 情報源分析 | E-1引用の推移 + 掲載依頼先の候補 |
| R7 | KGI | 週計カード + 波及順序 |
| R8 | アクションボード | action_log の一覧と状態 |

旧P3(プロンプト詳細)・旧P4(回答ビューア)・旧P5(週次所見)は
サイドバー下部の「詳細」に残し、R4・R6からの深掘り先とする。

### 判定欄(全面共通・最重要)

各面の下部に「判定:」で始まる1〜3文を出す。**LLMは使わない。**
条件分岐と文面は `config/verdict_templates.yaml` にあり、コードは条件評価と
実値の差し込みだけを行う。

```yaml
R3:
  - id: r3_within_window
    when:
      negative_streak_days: {">=": 1}
      days_since_last_action: {"<": 28}
    text: "「{last_action_name}」から{days_since_last_action}日、…"
```

- 判定欄は毎週同じ基準で読まれる。同じ状態なら同じ文が出ることが前提で、
  言い回しが週ごとに揺れると「変わったのは状態か文章か」が判別できなくなる。
- 各面に最低2分岐(正常系/要対応系)。判断期限・次の施策は `action_log` から取る。
- **「直近の施策」は面ごとに関係する施策だけから選ぶ。** 全施策から最新を取ると、
  ネガ検知の面にKGI向けの施策が出てしまうため。

  | 面 | 参照する施策 |
  |---|---|
  | R3 ネガ検知 | 根拠rule_id が `R-P7` / `R-P8` のもの |
  | R7 KGI | 対象が `KGI` のもの |
  | その他 | 全施策から最新 |
- テンプレートにない変数を書くと例外で落ちる(静かに空欄にしない)。
- 文面の原則:比喩を使わない / 英語表記を使わない(製品名・システム名を除く) /
  数値は実値のみ。テストで固定している。

### action_log(施策記録)

**状態列は本田さんがシート上で直接編集する。アプリからは書かない。**
週次所見の「アクション:」行だけが「提案中」で自動追記される(§5)。
同一内容 + 同一rule_id が未完了状態で存在すれば追記しない。

| 状態 | 意味 |
|---|---|
| 提案中 / 承認待ち | 週次所見が出した候補 / 検討対象として残したもの |
| 承認 | やると決めたが未着手 |
| 実施済み・効果測定中 | **R2・R3に縦線注釈が出る** |
| 完了 / 却下 / 保留 | 終わった / やらない / 時期を待つ |

初期データ A-001〜A-007 は `cd src && python action_log.py --seed` で投入する
(`--dry-run` で確認可能)。

### citation_gap(引用元の3分類)

引用ドメインを「自社 / 共通 / 自社不在」に分ける。**自社不在**は、AIがその質問に
答えるとき見ているのに自社が載っていない場所で、掲載依頼先の候補になる。

データ源は `data/raw` の `cited_urls`。`llm_observations` は承認済みスキーマに
`all_cited_urls` を持たないため生データから再構成する(ローカル読みなのでAPIを消費しない)。
Geminiの引用は解決できない形式のため件数だけ報告して集計から除く。

### R5 の縦軸について(既知の制約)

散布図の縦軸は、**推薦リスト内の実順位を抽出しているのは自社のみ**である。
競合の縦軸は言及シェア順位による代理値で、競合の実順位ではない。
§4の抽出スキーマは `rank`(自社の推薦リスト内順位)しか持たないため。

> **将来のスキーマ改訂時の候補**
> `competitors_mentioned` を「社名の配列」から「社名と推薦リスト内順位の組」に
> 拡張すれば、競合の実順位で散布図を描ける。
> ただし §4 の抽出スキーマは凍結中のため、本Phaseでは行わない。
> 改訂する場合は llm_observations の列追加・過去データの再抽出コスト・
> 抽出精度への影響(順位の誤りが増えないか)を併せて検討する。

### board_daily(Looker Studio 用)

1日1行のフラットタブ。移動平均・週計・連続日数まで確定させてあるので、
Looker側で計算しなくても読める。Looker Studio 自体の再構築は本Phaseの対象外。

---

## Phase 6:Looker Studio 統合(表示用データ層)

Looker Studio はレイアウトをAPIで構築できない。そこで**計算・判定・整形をすべて
パイプライン側で終わらせ、Looker は「シートのタブを置くだけ」で8面相当が組める
状態**にした。順位の代理値・四象限・期限までの日数のように、本来なら Looker 側の
計算フィールドになるものも `lk_*` タブに確定値として入っている。

### lk_* タブと8面の対応

| タブ | 対応する面 | 主な列 | 鍵(冪等更新の単位) |
|---|---|---|---|
| `lk_verdicts` | R1〜R8 すべて | `face` / `face_name` / `verdict_text` | date × face |
| `lk_heatgrid` | R4 獲得マップ | `prompt_name` / `days_mentioned_7d` / `cell_label` | date × prompt_id × model |
| `lk_scatter` | R5 競合ポジション | `share_28d` / `rank_median` / `rank_source` / `quadrant` | date × entity |
| `lk_sov_trend` | R2・R5 | `share_7d`(7日移動平均済み) / `is_crosscom` | date × entity |
| `lk_negative` | R3 ネガ検知 | `detected`(1/0) / `note`(種別要約20字以内) | date × model |
| `lk_events` | R1・R3 | `event_name`(日本語) / `place` / `playbook_ref` | date × event_type × place × detail |
| `lk_actions` | R8 アクションボード | `target_display` / `days_to_deadline` | action_id |
| `lk_answers` | 詳細:回答 | `answer_text`(直近14日・40,000字で切り詰め) | date × prompt_id × model |
| `board_daily` | R1 サマリ | 既存の列 + `verdict_r1` | date |

既存の `citation_gap` / `action_log` はそのまま使う(`lk_actions` は `action_log` の
**表示用ミラー**で、元のタブは本田さんの編集用として不変)。

### 読み方の注意

- **`lk_scatter` の `rank_median` は自社だけが実順位。** 競合は言及シェアの順位を
  代理値として置いている(§4の抽出スキーマ凍結のため競合の実順位は取得していない)。
  代理値である以上シェアと順位が同じ並びになるので、**競合の `quadrant` は
  「高シェア×上位」か「低シェア×下位」のどちらかにしかならない**。四象限が意味を
  持つのは自社の位置だけ。`rank_source` 列でどちらの根拠かを判別できる。
- **`lk_events` の「競合上位入り」は当日の言及シェア上位5社に限る。** 回答に一度
  出ただけの社名まで載せるとイベント表が埋まって読めなくなる。
- **`lk_verdicts` の過去日は「その日までに存在していた施策」だけを見て作る。**
  施策の状態はシートの現在値しか残っていないため過去の状態は復元できないが、
  少なくともその日にまだ提案も実施もされていない施策は持ち込まない
  (これを入れないと「実施から-47日」のような文が並ぶ)。

### 実行

日次(`run_daily.py`)の末尾で `lk_*` 一式を書き出す。書き込みはタブ数によらず
**1回の `values_batch_update`** にまとめている。週次(`run_weekly.py`)は
`citation_gap` 更新後に `lk_scatter` を取り直す(28日窓の集計なので、日次の
追記だけでは引用元の入れ替わりが反映されきらない)。

過去分は手動ワークフロー `backfill-looker`(または直接実行)で作る:

```
python scripts/backfill_looker.py --dry-run
python scripts/backfill_looker.py
python scripts/backfill_looker.py --since 2026-08-01 --tabs lk_sov_trend,lk_negative
```

対象は `lk_sov_trend` / `lk_negative` / `lk_verdicts` の3つ。残りは当日の
スナップショットなので過去分を作る意味がない。二度実行しても行は増えない。

### 追加で読むタブ

日次は `llm_observations` に加えて `ga4_ai_traffic` / `gsc_branded` / `action_log`
を読む。前2つは週計を出すのに履歴が要る(`collect_ga4` / `collect_gsc` は当日分
しか返さない)ため、`action_log` は `lk_actions` の元になるため。言及率と言及
シェアの履歴は `llm_observations` から同じ式で復元できるので、`daily_summary` と
`sov_daily` は読み直していない。

---

## Looker Studio 接続手順

### 1. データソースを追加

| データソース | コネクタ | 用途 |
|--------------|----------|------|
| Google Sheets → `daily_summary` | **Sheetsコネクタ** | スコアカード・時系列(KGI/KPIサマリ) |
| Google Sheets → `llm_observations` | **Sheetsコネクタ** | KPI詳細(モデル別・プロンプト別・KBF) |
| GA4 プロパティ | **GA4ネイティブコネクタ** | AI経由流入の深掘り(任意) |
| Search Console | **GSCネイティブコネクタ** | 指名検索の深掘り(任意) |

> `date` 列は Sheets 側でテキスト保存されるため、Looker 側でフィールドの型を「日付(YYYY-MM-DD)」に変更する。

### 2. 推奨チャート構成

**ページ1:サマリ(daily_summary)**
- スコアカード:`mention_rate_all`(最新日)、`negative_flag_count`、`ai_sessions`、`branded_clicks`
- 時系列グラフ:`date` × `mention_rate_all` / `mention_rate_pillar_a` / `mention_rate_pillar_b`(3系列)
- 時系列グラフ:`date` × `ai_sessions` と `branded_clicks`(2軸)

**ページ2:KPI詳細(llm_observations)**
- ピボットテーブル:行 `prompt_id`、列 `model`、値 `mention`(TRUE比率)/ 平均 `rank`
- 積み上げ棒:`kbf_tags` の出現頻度(どのKBFで想起されているか)
- 表:`negative_or_outdated = TRUE` の行(`negative_detail`, `model`, `date`)= 是正対象
- 表:`competitors_mentioned` の頻出社名(競合の想起状況)

**ページ3:KGI(GA4 / GSC ネイティブ)**
- GA4:AI経由 source 別 sessions / key_events、ランディングページ別
- GSC:指名検索 query 別 clicks / impressions の推移

**ページ4:競合SoVと変化(sov_daily / changes)**
- 100%積み上げ棒:`date` × `entity`(値 `mention_count`、`pillar = all` でフィルタ)
- 計算フィールド `share = mention_count / observed_total` を作り、自社(`entity = クロスコム`)の推移を時系列表示
- 表:`changes` を `date` 降順(`change_type` / `prompt_id` / `model` / `detail`)= 日々の動きの一覧
- `pillar` はコントロール(A / B / all)にして切り替える。`all` と A/B を同時に出すと二重計上になる

### 3. スプレッドシート凡例タブへの追記

Phase 1 で追加した2タブぶんの凡例。凡例タブへそのまま貼り付ける(タブ区切り):

```
sov_daily	date	観測日
sov_daily	pillar	集計対象Pillar(A/B/all。E-1除外)
sov_daily	entity	正規化済み企業名(自社含む)
sov_daily	mention_count	当日の言及回数
sov_daily	observed_total	当日の観測数(シェアの分母)
changes	change_type	前回観測からの変化種別(言及獲得/消失・順位変動・競合出入り・引用URL出入り・ネガティブ変化)
changes	before/after	変化前後の値
changes	detail	補足(企業名・URL等)
```

---

## 概算コスト

LLM API は **日次 14クエリ(観測:gemini/claude × 7)+ 14回(抽出)= 28 API呼び出し/日**。

| 項目 | 単価目安 | 月間(30日) |
|------|----------|-------------|
| 観測 Gemini(2.5 flash + grounding)× 7/日 | ~$0.005/回 | ~$1 |
| 観測 Claude(sonnet + web search)× 7/日 | ~$0.02/回 | ~$4 |
| 抽出 Anthropic Haiku × 14/日 | ~$0.002/回 | ~$0.9 |
| 週次所見 Claude Sonnet × 4-5回/月 | ~$0.03/回 | ~$0.15 |
| **合計** | | **≈ $6 ≒ 月900〜1,000円** |

- **想定:LLM API 合計 月2,000円以内**に収まる(chatgpt を有効化しても +$3–4/月で 2,000円以内)。
- **Phase 2 の週次所見は月4〜5回のSonnet呼び出しのみ**で、入力は stats.json(数KB)に限定される。
  raw回答を渡さない設計のため **月100円未満**(想定 ~$0.15)。想定コストへの影響はほぼない。
- Web検索ツールの利用料はモデル・プラン依存。上振れする場合は `EXTRACT_MODEL` を最安モデルに固定、観測モデルを絞る(`ENABLE_*`)ことで調整可能。
- GA4 / GSC / Sheets API、GitHub Actions(パブリック/一定枠内)は無料枠で運用。
- Ahrefs は既存 Lite プラン範囲(追加課金なし、AI Overview エンドポイントが 402/403 の場合はスキップ)。

---

## 完成条件(Definition of Done)対応

1. `workflow_dispatch` で `daily.yml` を手動実行 → 全タブにデータ書き込み。
2. `data/raw/` に 14件のJSON(7プロンプト × 有効2モデル、欠損はエラー記録)を保存・commit。
3. 同日2回実行しても `date × prompt_id × model` 主キーで上書きされ重複しない。
4. 本READMEにアーキテクチャ・Secrets一覧・Looker Studio接続手順を記載。
5. 概算コスト(月2,000円以内想定)を明記。

### Phase 1 追加分

6. `normalize_entity` のユニットテスト(全角/法人格/エイリアス統合)が通る。
7. 前回データなしの `analyze_diff` が「差分なし」で正常終了する。
8. 差分検出(mention flip / rank変化 / 競合追加削除)を合成データで検証済み。
9. `workflow_dispatch` 実行で `sov_daily` にデータが入り、2回実行しても
   `date × pillar × entity` 主キーで重複しない。
10. `python notify_slack.py --test` で疑似アラートを1通送信できる。
11. 本READMEに Phase 1 の内容と凡例追記を反映。
12. 正規化の取りこぼし(`100` 行・EY空白ゆれ・一般名詞の混入)を修正し、
    `backfill_sov.py` で `sov_daily` を全期間再生成できる。

### Phase 2 追加分

13. 全7ルールのユニットテスト(発火/非発火/insufficient_data)が通る。
14. `workflow_dispatch` 実行でSlackに週次所見が届き、`weekly_reports` タブに保存される。
15. 所見文の数値は stats.json のみを根拠とする(プロンプトで明示禁止 + フォールバックは構造的に一致)。
16. LLM呼び出し失敗をシミュレートしてもフォールバック配信される(`test_run_weekly.py` で検証)。
17. 本READMEに Phase 2 の構成図・週次運用フロー・コストを記載。

### Phase 5 追加分

22. run_dashboard.bat 起動で R1〜R8 が実データで表示される。
23. 各面に判定欄が出る。文面は verdict_templates.yaml 由来で、
    YAMLを差し替えれば文が変わることをテストで固定(`test_verdicts.py`)。
24. R2・R3 に A-001〜A-005 の縦線注釈が出る。
25. citation_gap・action_log・board_daily タブにデータが入っている。
26. 判定テンプレート分岐・不在引用元の3分類・action_log重複防止のテストが通る。

### Phase 4 追加分

18. `setup_dashboard.bat` → `run_dashboard.bat` の2ステップでブラウザにアプリが開く。
19. 5ページすべてが表示される(P4は実データ、P1〜P3/P5はサンプルモードで動作確認済み)。
20. 認証JSON欠如時の劣化動作が仕様どおり(案内表示 + P4は通常動作)。
21. 本READMEにセットアップ手順とサービスアカウントJSONの配置場所を記載。
