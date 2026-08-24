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
│   └── backfill_sov.yml   # sov_daily 全期間再生成(手動実行)
├── config/
│   ├── prompts.yaml       # 観測プロンプト定義(承認済み・変更禁止)
│   ├── entity_aliases.yaml  # 企業名エイリアス(運用中に追記する)
│   ├── entity_stoplist.yaml # 企業名でない一般名詞の除外リスト
│   ├── playbook.md          # 運用プレイブック(Phase 2・所見生成の根拠)
│   ├── rules_thresholds.yaml # ルール閾値(Phase 2・コード変更なしで調整)
│   └── legacy_paths.yaml    # 旧事業URLパス(Phase 2 R-P8)
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
│   ├── collect_ga4.py     # GA4:AI経由流入・CV
│   ├── collect_gsc.py     # GSC:指名検索
│   ├── collect_ahrefs.py  # 週次:AI Overviews引用KW(失敗時スキップ可)
│   ├── sheets_writer.py   # Sheets追記の共通処理(冪等upsert)
│   ├── settings.py        # 環境変数・定数・モデル有効/無効
│   ├── run_daily.py       # 日次オーケストレータ
│   └── run_weekly.py      # 週次オーケストレータ
├── app/                   # ローカル分析アプリ(Phase 4・Streamlit・読み取り専用)
│   ├── main.py            # エントリポイント(5ページのナビゲーション)
│   ├── data_source.py     # Sheets/ローカルの読み取りとキャッシュ
│   ├── common.py          # 共通ヘルパー(パース・チャート配色)
│   ├── sample_data.py     # 認証なしでUIを確認するためのサンプル
│   └── views/             # P1〜P5 の各ページ
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
```

**読み方の注意**

- `daily_summary.negative_flag_count` と P-7 のネガ検知は、**8/24 の前後で定義が違う**。
  8/24 より前の値は、再抽出した行については新基準、それ以外は旧基準のままである。
- `config/legacy_paths.yaml`(P-8)には**同じ3区分の混同が残っている**。
  `/marketing-automation-btob/` `/ma-tool/` `/mail-magazine/` は現行・非注力事業の
  ページであり、引用されること自体は汚染ではない。純粋な終了事業パスは
  `/btob-marketing-strategy/` のみ。**未処置**(本田さんの判断待ち)。
- `/btob-crm/` は 2026-08-24 時点で **404(実在しない)**。AIが存在しないURLを引用していた
  ハルシネーションだが、検知は継続するため定義からは削除していない。

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

### 3. `config/playbook.md` — 所見の根拠

`generate_insight.py` が「原因仮説」と「改善策」を書く際の**唯一の根拠**。
P-2 / P-4 / P-5 / P-7 / P-8 / P-15 / P-DROP それぞれについて
**状態 → 原因仮説 → 改善アクション** を定義している。

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
python notify_slack.py --test-weekly --date 2026-08-17               # 週次投稿のテスト送信
```

**終了コードの約束**:Ahrefs の失敗は best-effort なので緑のまま。
それ以外の失敗(所見のフォールバック使用を含む)は**赤にする** —
数値だけのレポートが届いたことに気付けるようにするため。

---

## Phase 4:ローカル分析アプリ(Streamlit)

日常のグラフ確認は Looker Studio、**回答全文・差分・所見まで一画面で追う深掘り分析**はこのアプリ。
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

### Phase 4 追加分

18. `setup_dashboard.bat` → `run_dashboard.bat` の2ステップでブラウザにアプリが開く。
19. 5ページすべてが表示される(P4は実データ、P1〜P3/P5はサンプルモードで動作確認済み)。
20. 認証JSON欠如時の劣化動作が仕様どおり(案内表示 + P4は通常動作)。
21. 本READMEにセットアップ手順とサービスアカウントJSONの配置場所を記載。
