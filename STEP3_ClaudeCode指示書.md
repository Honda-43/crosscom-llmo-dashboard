# STEP 3:Claude Code実装指示書 — LLMOモニタリングダッシュボード

## 0. このプロジェクトの目的

cross-com.jp のLLMO対策の成果を日次で観測するデータパイプラインを構築する。
KGI(指名検索・AI経由流入)とKPI(AI内での推薦のされ方・語られ方の質)の2階層を、
GitHub Actionsによる毎朝の自動収集 → Google Sheets蓄積 → Looker Studio可視化で運用する。

Brand Radar(Ahrefs)はLiteプランで利用不可のため、LLM API定点観測スクリプトで代替する。
これが本システムの核である。

## 1. リポジトリ構成

```
crosscom-llmo-dashboard/
├── .github/workflows/
│   ├── daily.yml          # 毎朝07:00 JST(cron: '0 22 * * *' UTC)
│   └── weekly.yml         # 毎週月曜08:00 JST(cron: '0 23 * * 0' UTC)
├── config/
│   └── prompts.yaml       # 観測プロンプト定義(§2)
├── src/
│   ├── collect_llm.py     # 4モデルへの定点観測クエリ実行
│   ├── extract.py         # 回答テキストからの構造化抽出
│   ├── collect_ga4.py     # GA4:AI経由流入・CV
│   ├── collect_gsc.py     # GSC:指名検索
│   ├── collect_ahrefs.py  # 週次:AI Overviews引用KW(失敗時スキップ可)
│   ├── sheets_writer.py   # Sheets追記の共通処理
│   └── settings.py        # 環境変数・定数
├── data/raw/              # LLM回答全文の保存先(git管理、日付ディレクトリ)
├── requirements.txt
└── README.md
```

## 2. 観測プロンプト定義(config/prompts.yaml)— 承認済み・変更禁止

```yaml
prompts:
  - id: A-1
    pillar: A
    text: "Agentforceの導入支援をしてくれるおすすめの会社を教えてください"
    cep: "導入検討初期・パートナー探し"
  - id: A-2
    pillar: A
    text: "Agentforceを導入したが現場に定着しない。定着支援や活用支援をしてくれるコンサルはありますか"
    cep: "導入後の定着課題"
  - id: A-3
    pillar: A
    text: "Agentforceの導入費用の相場と、費用対効果を出すための進め方を教えてください"
    cep: "料金比較・稟議準備"
  - id: B-1
    pillar: B
    text: "Agentic CRMとは何ですか。導入や設計を支援してくれる会社はありますか"
    cep: "カテゴリ認知+支援会社探し"
  - id: B-2
    pillar: B
    text: "中堅企業です。特定ベンダーに依存せず中立的な立場でCRMの設計を支援してくれる会社を探しています"
    cep: "ベンダー中立ポジション"
  - id: B-3
    pillar: B
    text: "営業にAIエージェントを活用したい。ツール選定の前にCRMのデータ設計から支援してくれるパートナーはいますか"
    cep: "設計ファースト方法論"
  - id: E-1
    pillar: entity
    text: "合同会社クロスコムはどんな会社ですか。強みと提供サービスを教えてください"
    cep: "エンティティ情報の鮮度"
```

## 3. collect_llm.py — 定点観測(初期3モデル構成)

モデルはsettings.pyで有効/無効を切替可能にし、**初期状態はPerplexityを無効**とする
(有効:chatgpt / gemini / claude)。日次観測は7プロンプト × 3モデル = 21クエリ。
各回答の全文を `data/raw/YYYY-MM-DD/{prompt_id}_{model}.json` に保存
(質問・回答・引用URL・タイムスタンプ)。

| モデルキー | 初期状態 | API | 必須設定 |
|-----------|---------|-----|---------|
| chatgpt | 有効 | OpenAI Responses API | `tools: [{"type": "web_search"}]`、モデルは現行の標準モデル(gpt-4oクラス以上) |
| gemini | 有効 | Gemini API | `tools: [{"google_search": {}}]`(Grounding with Google Search) |
| claude | 有効 | Anthropic Messages API | web searchツール有効。現行標準モデル |
| perplexity | **無効** | Perplexity API | モデル `sonar`。citationsフィールドを保存。`PERPLEXITY_API_KEY` が未設定でもエラーにならないこと。将来キー登録+フラグ変更のみで有効化できる実装にする |

共通要件:
- system指示は付けない(素のユーザー質問として投げ、実利用者の体験を再現する)
- temperatureはデフォルトのまま
- リトライ:指数バックオフで最大3回。3回失敗したモデルは当日欠損として記録し、他モデルの処理は継続
- 引用URL:各APIのネイティブなcitation/annotationフィールドから取得し、本文中のURLと統合

## 4. extract.py — 構造化抽出

保存した回答全文を、Anthropic API(コスト最小の現行モデル、例:Haiku系)で
以下のJSONスキーマに抽出する。1回答=1抽出呼び出し。

```json
{
  "mention": true,
  "mention_type": "recommended_list",  // recommended_list | mentioned_only | none
  "rank": 2,                            // 推薦リスト内順位。リスト外・言及なしはnull
  "kbf_tags": ["ベンダー中立", "定着支援"],
  // 選択肢: ベンダー中立 / 設計支援 / 定着支援 / Agentforce専門性 /
  //         ソリューション営業知見 / 実績・事例 / その他
  "negative_or_outdated": false,
  "negative_detail": null,              // 旧MA/メール配信事業の記述、誤情報等があれば内容を記載
  "cited_crosscom_urls": ["https://cross-com.jp/..."],
  "all_cited_urls": ["..."],
  "competitors_mentioned": ["社名1", "社名2"]
}
```

抽出プロンプトの要件:
- 「クロスコム」「合同会社クロスコム」「cross-com」「Crosscom」の表記ゆれをすべて自社言及と判定
- E-1プロンプトはmention判定不要(必ず言及される)。negative_or_outdatedとkbf_tagsの精度を優先
- 抽出結果のJSONバリデーションに失敗したら1回だけ再抽出、それでも失敗なら該当行をerror記録

## 5. collect_ga4.py / collect_gsc.py

**GA4(日次)**:runReportで前日分を取得。
- dimensions: `date`, `sessionSource`, `landingPagePlusQueryString`
- metrics: `sessions`, `keyEvents`
- フィルタ: sessionSourceが次のいずれかを含む
  `chatgpt.com`, `chat.openai.com`, `perplexity.ai`, `gemini.google.com`,
  `copilot.microsoft.com`, `claude.ai`, `bing.com/chat`

**GSC(日次)**:3日前の日付分を取得(データ確定遅延対策)。
- dimensions: `query`, `date`
- フィルタ: queryに `クロスコム` / `crosscom` / `cross-com` / `cross com` のいずれかを含む
- clicks / impressions を集計

## 6. collect_ahrefs.py(週次・ベストエフォート)

Ahrefs API v3 `site-explorer/organic-keywords` で target=cross-com.jp、
SERP featuresに AI Overview を含むキーワードの件数と一覧を取得する。
Liteプランの制約でエンドポイントが403/402を返す場合は、警告ログのみ出して
正常終了すること(パイプライン全体を落とさない)。

## 7. Google Sheets スキーマ(sheets_writer.py)

スプレッドシートに以下のタブを自動作成し、日次追記(ロングフォーマット)する。

**タブ1: llm_observations**(1行 = 1日 × 1プロンプト × 1モデル)
| date | prompt_id | pillar | model | mention | mention_type | rank | kbf_tags | negative_or_outdated | negative_detail | cited_crosscom_urls | competitors_mentioned | raw_file |

**タブ2: ga4_ai_traffic**
| date | source | landing_page | sessions | key_events |

**タブ3: gsc_branded**
| date | query | clicks | impressions |

**タブ4: ahrefs_aio**(週次)
| date | aio_keyword_count | keywords_json |

**タブ5: daily_summary**(日次サマリ:ダッシュボードのスコアカード用)
| date | mention_rate_all | mention_rate_pillar_a | mention_rate_pillar_b | negative_flag_count | ai_sessions | branded_clicks |

- mention_rateは当日の有効観測数(E-1を除く6プロンプト × 有効モデル数。初期は18観測)に対するmention=true比率。有効モデル数に連動させ、固定値をハードコードしない
- 冪等性:同一date×prompt_id×modelの行が既に存在する場合は上書き(再実行安全)

## 8. GitHub Actions

**daily.yml**(07:00 JST)
1. collect_llm.py → extract.py → sheets_writer(タブ1・5)
2. collect_ga4.py → タブ2
3. collect_gsc.py → タブ3
4. data/raw/ の新規ファイルをcommit & push
5. いずれかのステップが失敗してもワークフロー全体は最後まで実行し、失敗はジョブサマリに明記

**weekly.yml**(月曜08:00 JST)
- collect_ahrefs.py → タブ4

手動実行(workflow_dispatch)も両方に付けること。

## 9. 完成条件(Definition of Done)

1. `workflow_dispatch` で daily.yml を手動実行し、全タブにデータが書き込まれる
2. data/raw/ に21件のJSON(7プロンプト × 有効3モデル。欠損時はエラー記録)が保存される
3. 同日2回実行しても行が重複しない
4. README.md に:アーキテクチャ図(テキストで可)、Secrets一覧、Looker Studio接続手順
   (GA4/GSCネイティブコネクタ+Sheetsコネクタでタブ1・5を接続、推奨チャート構成)を記載
5. 概算コストがREADMEに明記されている(LLM API合計 月2,000円以内を想定)

## 10. 実装時の判断ルール

- 本指示書にない技術選択(ライブラリ等)はClaude Codeの判断で決めてよい
- ただし §2 のプロンプト文言、§4 の抽出スキーマ、§7 のシートスキーマは
  戦略チャット側で承認済みのため変更しない。変更が必要な場合は実装を止めて報告する
