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
 weekly.yml 月08:00 JST ─▶│  run_weekly.py                               │
 (cron: 0 23 * * 0 UTC) │   └─ collect_ahrefs.py ─▶ tab4 (best-effort) │
                         └───────────────────────────┬──────────────────┘
                                                     │
                              ┌──────────────────────▼───────────────────┐
                              │           Google Sheets(7タブ)          │
                              │  llm_observations / ga4_ai_traffic /     │
                              │  gsc_branded / ahrefs_aio / daily_summary│
                              │  sov_daily / changes        (Phase 1)    │
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

---

## リポジトリ構成

```
crosscom-llmo-dashboard/
├── .github/workflows/
│   ├── daily.yml          # 毎朝07:00 JST(cron: '0 22 * * *' UTC)
│   ├── weekly.yml         # 毎週月曜08:00 JST(cron: '0 23 * * 0' UTC)
│   └── backfill_sov.yml   # sov_daily 全期間再生成(手動実行)
├── config/
│   ├── prompts.yaml       # 観測プロンプト定義(承認済み・変更禁止)
│   ├── entity_aliases.yaml  # 企業名エイリアス(運用中に追記する)
│   └── entity_stoplist.yaml # 企業名でない一般名詞の除外リスト
├── src/
│   ├── collect_llm.py     # 4モデルへの定点観測クエリ実行
│   ├── extract.py         # 回答テキストからの構造化抽出
│   ├── normalize.py       # 企業名の正規化(Phase 1 §2-1)
│   ├── analyze_sov.py     # 競合Share of Voice集計(Phase 1)
│   ├── analyze_diff.py    # 前回観測との差分検出(Phase 1)
│   ├── notify_slack.py    # Slackアラート(Phase 1)
│   ├── backfill_sov.py    # sov_daily の全期間再生成(Phase 1)
│   ├── collect_ga4.py     # GA4:AI経由流入・CV
│   ├── collect_gsc.py     # GSC:指名検索
│   ├── collect_ahrefs.py  # 週次:AI Overviews引用KW(失敗時スキップ可)
│   ├── sheets_writer.py   # Sheets追記の共通処理(冪等upsert)
│   ├── settings.py        # 環境変数・定数・モデル有効/無効
│   ├── run_daily.py       # 日次オーケストレータ
│   └── run_weekly.py      # 週次オーケストレータ
├── tests/                 # pytest(正規化・SoV・差分検出・Slack・backfill)
├── data/raw/              # LLM回答全文の保存先(git管理、日付ディレクトリ)
├── requirements.txt
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

---

## Secrets 一覧(GitHub Actions Secrets に登録)

| Secret | 必須 | 用途 |
|--------|------|------|
| `GEMINI_API_KEY` | ○ | Gemini 定点観測 |
| `ANTHROPIC_API_KEY` | ○ | Claude 定点観測 + `extract.py` 構造化抽出 |
| `OPENAI_API_KEY` | – | ChatGPT(有効化時のみ) |
| `PERPLEXITY_API_KEY` | – | Perplexity(有効化時のみ) |
| `GCP_SERVICE_ACCOUNT_JSON` | ○ | サービスアカウントJSON(Sheets / GA4 / GSC 共通) |
| `SHEETS_SPREADSHEET_ID` | ○ | 出力先スプレッドシートID |
| `GA4_PROPERTY_ID` | ○ | GA4 プロパティID(数値) |
| `GSC_SITE_URL` | ○ | 例 `sc-domain:cross-com.jp` または `https://cross-com.jp/` |
| `AHREFS_API_KEY` | – | 週次 Ahrefs(ベストエフォート) |
| `SLACK_WEBHOOK_URL` | – | Slackアラート(未設定なら警告ログのみでスキップ) |

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
| `sov_daily`(Phase 1) | 1日×pillar×企業 | date, pillar, entity, mention_count, observed_total |
| `changes`(Phase 1) | 変化1件 | date, prompt_id, model, change_type, before, after, detail |

- **mention_rate** は当日の**有効観測数**(E-1を除く6プロンプト × 有効モデル数。初期は gemini / claude の2モデルで12観測)に対する `mention=true` 比率。有効モデル数に連動し、固定値はハードコードしない(モデルを増減すれば分母も自動追随)。
- **冪等性**:同一 `date × prompt_id × model` の行が既に存在する場合は上書き(同日再実行安全)。各タブとも主キーで upsert する。
- 抽出/観測に失敗した行も欠損として書き込み(`negative_detail` に `[error] ...` を記録)、`daily_summary` の分母からは除外する。

> 補足:`daily_summary.ai_sessions` は GA4(前日分)、`branded_clicks` は GSC(3日前分)の当日収集値を集計。
> LLM観測日(当日)を主キーとしたスナップショット行のため、各源の対象日付にはデータ確定遅延分のズレがある。

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

- **Slack Incoming Webhook**(無料)を使用。Secret名 `SLACK_WEBHOOK_URL`。
- **未設定でもパイプラインは落ちない**(警告ログとメッセージ本文を標準出力に出して正常終了)。
- 通知条件(当日分)と表示順:

  1. ⚠️ **ネガティブ/誤情報検知** — `negative_or_outdated=TRUE` または `negative_flag_on`(**必ず先頭**)
  2. 📈 **言及獲得** / 📉 **言及消失** — `mention_gained` / `mention_lost`
  3. ❌ **パイプライン一部失敗** — 失敗フェーズ名とエラー要約

- 該当が1件もない日は**通知を送らない**(ゼロ通知が正常)。
- 日本語・1日1投稿(セクション分け)。文末に `SHEETS_SPREADSHEET_ID` から生成した
  スプレッドシートURLを付ける。
- Python到達前にワークフローが落ちた場合(checkout / pip install の失敗など)は、
  `daily.yml` 最終stepの `if: failure()` が Webhook へ直接POSTする。

**テスト送信**(疑似アラートを1通送る):

```bash
cd src && SLACK_WEBHOOK_URL=... python notify_slack.py --test
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
| **合計** | | **≈ $6 ≒ 月900〜1,000円** |

- **想定:LLM API 合計 月2,000円以内**に収まる(chatgpt を有効化しても +$3–4/月で 2,000円以内)。
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
