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
  (cron: 0 22 * * * UTC) │   ├─ collect_llm.py  ── 7 prompts × 3 models │
                         │   │      │  (ChatGPT / Gemini / Claude)      │
                         │   │      └─▶ data/raw/YYYY-MM-DD/*.json ──┐   │
                         │   ├─ extract.py (Anthropic Haiku) ◀───────┘   │
                         │   │      └─▶ 構造化(§4スキーマ)             │
                         │   ├─ collect_ga4.py ── AI経由流入(前日)     │
                         │   ├─ collect_gsc.py ── 指名検索(3日前)      │
                         │   └─ sheets_writer.py ─▶ Google Sheets       │
                         │                                              │
 weekly.yml 月08:00 JST ─▶│  run_weekly.py                               │
 (cron: 0 23 * * 0 UTC) │   └─ collect_ahrefs.py ─▶ tab4 (best-effort) │
                         └───────────────────────────┬──────────────────┘
                                                     │
                              ┌──────────────────────▼───────────────────┐
                              │           Google Sheets(5タブ)          │
                              │  llm_observations / ga4_ai_traffic /     │
                              │  gsc_branded / ahrefs_aio / daily_summary│
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

---

## リポジトリ構成

```
crosscom-llmo-dashboard/
├── .github/workflows/
│   ├── daily.yml          # 毎朝07:00 JST(cron: '0 22 * * *' UTC)
│   └── weekly.yml         # 毎週月曜08:00 JST(cron: '0 23 * * 0' UTC)
├── config/
│   └── prompts.yaml       # 観測プロンプト定義(承認済み・変更禁止)
├── src/
│   ├── collect_llm.py     # 4モデルへの定点観測クエリ実行
│   ├── extract.py         # 回答テキストからの構造化抽出
│   ├── collect_ga4.py     # GA4:AI経由流入・CV
│   ├── collect_gsc.py     # GSC:指名検索
│   ├── collect_ahrefs.py  # 週次:AI Overviews引用KW(失敗時スキップ可)
│   ├── sheets_writer.py   # Sheets追記の共通処理(冪等upsert)
│   ├── settings.py        # 環境変数・定数・モデル有効/無効
│   ├── run_daily.py       # 日次オーケストレータ
│   └── run_weekly.py      # 週次オーケストレータ
├── data/raw/              # LLM回答全文の保存先(git管理、日付ディレクトリ)
├── requirements.txt
└── README.md
```

---

## モデル構成(初期状態)

| モデルキー | 初期状態 | API | 既定モデル |
|-----------|---------|-----|-----------|
| chatgpt | 有効 | OpenAI Responses API + `web_search` | `gpt-4o` |
| gemini | 有効 | Gemini API + Google Search Grounding | `gemini-2.5-flash` |
| claude | 有効 | Anthropic Messages API + Web Search | `claude-sonnet-5` |
| perplexity | **無効** | Perplexity API | `sonar` |

- 日次観測 = 7プロンプト × 有効3モデル = **21クエリ**。
- 有効/無効は `settings.py`(環境変数 `ENABLE_CHATGPT` / `ENABLE_GEMINI` / `ENABLE_CLAUDE` / `ENABLE_PERPLEXITY`)で切替。
- **Perplexity 有効化は「キー登録 + `ENABLE_PERPLEXITY=true`」のみでコード変更不要**。`PERPLEXITY_API_KEY` 未設定でもパイプラインはエラーにならない。
- モデル名は `OPENAI_MODEL` / `GEMINI_MODEL` / `ANTHROPIC_MODEL` / `EXTRACT_MODEL` で上書き可能。

---

## Secrets 一覧(GitHub Actions Secrets に登録)

| Secret | 必須 | 用途 |
|--------|------|------|
| `OPENAI_API_KEY` | ○ | ChatGPT 定点観測 |
| `GEMINI_API_KEY` | ○ | Gemini 定点観測 |
| `ANTHROPIC_API_KEY` | ○ | Claude 定点観測 + `extract.py` 構造化抽出 |
| `PERPLEXITY_API_KEY` | – | Perplexity(有効化時のみ) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | ○ | サービスアカウントJSON(Sheets / GA4 / GSC 共通) |
| `SHEET_ID` | ○ | 出力先スプレッドシートID |
| `GA4_PROPERTY_ID` | ○ | GA4 プロパティID(数値) |
| `GSC_SITE_URL` | ○ | 例 `sc-domain:cross-com.jp` または `https://cross-com.jp/` |
| `AHREFS_API_KEY` | – | 週次 Ahrefs(ベストエフォート) |

### サービスアカウントの権限付与

`GOOGLE_SERVICE_ACCOUNT_JSON` のサービスアカウントに以下を付与:

1. **Google Sheets** — 対象スプレッドシートをサービスアカウントのメールアドレスに「編集者」で共有。
2. **GA4** — 対象プロパティにサービスアカウントを「閲覧者」で追加(Data API 有効化)。
3. **GSC** — Search Console のプロパティにサービスアカウントを「制限付き」ユーザーとして追加(Search Console API 有効化)。

必要な OAuth スコープ(コード側で指定済み):
`spreadsheets` / `analytics.readonly` / `webmasters.readonly`。

### ローカル実行

```bash
pip install -r requirements.txt
export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat service_account.json)"   # or GOOGLE_APPLICATION_CREDENTIALS=path
export OPENAI_API_KEY=... GEMINI_API_KEY=... ANTHROPIC_API_KEY=...
export SHEET_ID=... GA4_PROPERTY_ID=... GSC_SITE_URL=sc-domain:cross-com.jp
cd src && python run_daily.py            # 日次
cd src && python run_weekly.py           # 週次(Ahrefs)
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

- **mention_rate** は当日の**有効観測数**(E-1を除く6プロンプト × 有効モデル数。初期は18観測)に対する `mention=true` 比率。有効モデル数に連動し、固定値はハードコードしない。
- **冪等性**:同一 `date × prompt_id × model` の行が既に存在する場合は上書き(同日再実行安全)。各タブとも主キーで upsert する。
- 抽出/観測に失敗した行も欠損として書き込み(`negative_detail` に `[error] ...` を記録)、`daily_summary` の分母からは除外する。

> 補足:`daily_summary.ai_sessions` は GA4(前日分)、`branded_clicks` は GSC(3日前分)の当日収集値を集計。
> LLM観測日(当日)を主キーとしたスナップショット行のため、各源の対象日付にはデータ確定遅延分のズレがある。

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

---

## 概算コスト

LLM API は **日次 21クエリ(観測)+ 21回(抽出)= 42 API呼び出し/日**。

| 項目 | 単価目安 | 月間(30日) |
|------|----------|-------------|
| 観測 ChatGPT(gpt-4o + web search)× 7/日 | ~$0.01–0.02/回 | ~$3–4 |
| 観測 Gemini(2.5 flash + grounding)× 7/日 | ~$0.005/回 | ~$1 |
| 観測 Claude(sonnet + web search)× 7/日 | ~$0.02/回 | ~$4 |
| 抽出 Anthropic Haiku × 21/日 | ~$0.002/回 | ~$1.3 |
| **合計** | | **≈ $9–11 ≒ 月1,400〜1,700円** |

- **想定:LLM API 合計 月2,000円以内**に収まる。
- Web検索ツールの利用料はモデル・プラン依存。上振れする場合は `EXTRACT_MODEL` を最安モデルに固定、観測モデルを絞る(`ENABLE_*`)ことで調整可能。
- GA4 / GSC / Sheets API、GitHub Actions(パブリック/一定枠内)は無料枠で運用。
- Ahrefs は既存 Lite プラン範囲(追加課金なし、AI Overview エンドポイントが 402/403 の場合はスキップ)。

---

## 完成条件(Definition of Done)対応

1. `workflow_dispatch` で `daily.yml` を手動実行 → 全タブにデータ書き込み。
2. `data/raw/` に 21件のJSON(7×3、欠損はエラー記録)を保存・commit。
3. 同日2回実行しても `date × prompt_id × model` 主キーで上書きされ重複しない。
4. 本READMEにアーキテクチャ・Secrets一覧・Looker Studio接続手順を記載。
5. 概算コスト(月2,000円以内想定)を明記。
