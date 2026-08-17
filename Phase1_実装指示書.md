# Phase 1 実装指示書 — SoV集計・差分検出・Slackアラート

対象リポジトリ:crosscom-llmo-dashboard
前提:daily パイプライン(collect_llm → extract → sheets_writer)は稼働済み。
本Phaseでは分析層の最初の3モジュールを追加する。既存の§2プロンプト・§4抽出スキーマ・
§7既存タブのスキーマは変更禁止。

---

## 1. 追加するモジュールと実行順

run_daily.py のフェーズ構成を以下に拡張する(既存フェーズの後段に追加、
フェーズ分離の設計は既存踏襲:1つ失敗しても後続は実行)。

```
collect_llm → extract → analyze_sov → analyze_diff
→ collect_ga4 → collect_gsc → build_summary → sheets書き込み → notify_slack
```

## 2. analyze_sov.py — 競合Share of Voice集計

**入力**:当日の抽出結果(extractの出力)+自社mention。
**処理**:
1. 各観測(prompt_id×model)の competitors_mentioned を展開し、自社(mention=TRUEの場合
   「クロスコム」として1カウント)と合わせてエンティティ別出現数を集計
2. エンティティ名の正規化を必ず通す(§2-1)
3. pillar別(A / B / all。E-1は除外)に集計

**§2-1 エンティティ名正規化(normalize_entity関数として独立実装・ユニットテスト必須)**:
- NFKC正規化(全角英数→半角、ＤＣＳ→DCS等)
- 法人格の除去:株式会社/合同会社/(株)/Inc./Co.,Ltd. 等を前後から除去
- 前後空白除去、社名内の中黒・スペースの統一
- `config/entity_aliases.yaml` によるエイリアス統合(正規化後に適用)。初期値:

```yaml
aliases:
  クロスコム: [cross-com, Crosscom, CROSSCOM]
  メンバーズ: [メンバーズ サースプラスカンパニー]
  三菱総研DCS: [DCS, 三菱総研ＤＣＳ]
  ゼロワングロース: [01GROWTH, 100inc]
  日立ソリューションズ: []
  テクノデジタルコンサルティング: []
  船井総合研究所: [船井総研]
```

- yamlは運用中に追記される前提。未知の企業名は正規化のみ適用しそのまま記録

**出力**:Sheetsタブ `sov_daily`(ロングフォーマット・冪等upsert)
| date | pillar | entity | mention_count | observed_total |

- observed_total = 当日の該当pillar観測数(シェア計算はLooker Studio/アプリ側で行うため
  分母を行に持たせる)

## 3. analyze_diff.py — 前回観測との差分検出

**入力**:当日と直前観測日の抽出結果(Sheetsのllm_observationsから直前日を取得。
初回実行など前回データがない場合は「差分なし」で正常終了)。
**処理**:prompt_id×model単位で以下のchange_typeを検出:

| change_type | 条件 |
|-------------|------|
| mention_gained | mention FALSE→TRUE |
| mention_lost | mention TRUE→FALSE |
| rank_up / rank_down | rank変化(数値小=上昇) |
| competitor_added / competitor_removed | 正規化後の競合集合の差分(企業名を記録) |
| crosscom_url_added / crosscom_url_removed | cited_crosscom_urlsの差分 |
| negative_flag_on / negative_flag_off | negative_or_outdatedの変化 |

**出力**:Sheetsタブ `changes`(変化があった行のみ追記・冪等)
| date | prompt_id | model | change_type | before | after | detail |

## 4. notify_slack.py — Slackアラート

**手段**:Slack Incoming Webhook(無料)。Secret名 `SLACK_WEBHOOK_URL`。
未設定の場合は警告ログのみで正常終了(パイプラインを落とさない)。

**通知条件(当日分)**:
1. 【最優先・必ず先頭】negative_flag_on または negative_or_outdated=TRUE の観測が存在
   → 「⚠️ ネガティブ/誤情報検知」+ prompt_id/model/negative_detail
2. mention_gained / mention_lost → 「📈 言及獲得」「📉 言及消失」+ prompt_id/model
3. いずれかのフェーズが失敗 → 「❌ パイプライン一部失敗」+ フェーズ名とエラー要約

該当がない日は通知を送らない(ゼロ通知が正常)。メッセージは日本語、1日1投稿に
まとめる(セクション分け)。文末にスプレッドシートURL(SHEETS_SPREADSHEET_IDから生成)を付ける。

## 5. GitHub Actions

- daily.yml に新フェーズが含まれることを確認(run_daily.py内の追加のみで完結する設計なら
  yml変更不要)。SLACK_WEBHOOK_URL を env に追加
- ワークフロー自体の失敗時通知として、最終stepに `if: failure()` でWebhookに直接POSTする
  stepを追加(Pythonまで到達しない失敗の捕捉)

## 6. テスト(Definition of Done)

1. normalize_entity のユニットテスト:全角/法人格/エイリアスの統合ケース
   (例:「株式会社メンバーズ サースプラスカンパニー」→「メンバーズ」、
   「三菱総研ＤＣＳ」→「三菱総研DCS」)が通る
2. 前回データなしでの analyze_diff が正常終了する
3. 差分検出のユニットテスト:mention flip / rank変化 / 競合追加削除を合成データで検証
4. workflow_dispatch 実行で sov_daily にデータが入り、2回実行しても重複しない
5. Slack通知のテスト:テスト用フラグ(--test)で疑似アラートを1通送信できる
6. README に Phase 1 の追加内容と凡例追記(下記)を反映

## 7. スプレッドシート凡例への追記(READMEに記載し、ユーザーが凡例タブへ貼る)

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

## 8. 実装時の判断ルール

- ライブラリ等の技術選択は自由。ただし新規の有料サービスは導入しない
- Sheets読み取りが増えるため、APIコール数に注意(既存のgspreadクライアントを共有し、
  タブ読み取りは1回にまとめる)
- 本指示書のタブスキーマ(sov_daily / changes)は承認済み。変更が必要な場合は実装を
  止めて報告する
