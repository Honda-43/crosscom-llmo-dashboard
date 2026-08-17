# Phase 2 実装指示書 — AI所見エンジン(週次自動レポート)

対象リポジトリ:crosscom-llmo-dashboard
前提:Phase 1(SoV・差分・Slack)稼働済み。
目的:蓄積データから「今週の状態判定と推奨アクション」を毎週自動生成し、
Slackに配信する。本田さんの週次レビューを「読んで承認するだけ」にする。

既存の§2プロンプト・§4抽出スキーマ・既存タブのスキーマは変更禁止。

---

## 1. 全体構成(2段階方式・重要)

判定と文章化を分離する:

- **第1段階(コード・決定的)**:ルール判定エンジンが統計値とパターン該当を機械的に算出
- **第2段階(Claude API)**:第1段階の結果**のみ**を材料に日本語の所見文を生成

LLMに生データの解釈や判定をさせない。判定はすべてテスト可能なコードで行う。

## 2. rules_engine.py — 第1段階:機械判定

**入力**:Sheetsの daily_summary / llm_observations / sov_daily / changes / ga4_ai_traffic / gsc_branded
(直近28日分。読み取りは既存gspreadクライアント共有・タブごと1回)

**出力**:stats.json(週次統計+発火ルール一覧)

### 2-1 週次統計(必ず算出)
- mention_rate 3系列:直近7日平均 vs 前週7日平均(差分付き)
- プロンプト×モデル別の言及状況マトリクス(直近7日:TRUE日数/観測日数)
- rank推移:prompt_id×modelごとの直近7日の中央値 vs 前週
- SoV上位10エンティティ(all/A/B別、直近7日集計)と前週比の増減
- changes集計:change_type別件数(直近7日)
- ga4:AI経由セッション週計 vs 前週 / gsc:指名クリック・インプレッション週計 vs 前週

### 2-2 パターン発火ルール(運用プレイブック準拠・機械判定のみ)

| rule_id | 発火条件(すべて機械的に判定可能なこと) |
|---------|------------------------------------------|
| R-P2 | 同一prompt_id×modelで、過去に言及実績があり、直近3観測日連続でmention=FALSE |
| R-P4 | pillar別mention_rate 7日平均が前週比+0.10以上 |
| R-P5 | 同一prompt_idでrank中央値が6以下(=6位以上悪い)の週が4週連続 |
| R-P7 | 直近7日にnegative_or_outdated=TRUEが1件以上(negative_detail同梱) |
| R-P8 | E-1のcited_crosscom_urlsに旧事業パス(/marketing-automation-btob/, /btob-marketing-strategy/, /btob-crm/ 等、config/legacy_paths.yamlで定義)が含まれる |
| R-P15 | 自社mention=FALSEのprompt_idにおいて、同一競合が直近7日で両モデル出現かつ4週連続出現 |
| R-DROP | SoV上位5の競合が前週比で出現半減、または新規エンティティが上位5入り |

- 各ルールは rule_id / 発火有無 / 根拠データ(該当prompt_id・企業名・数値)を出力
- データ不足で判定不能なルールは "insufficient_data" として明示(発火扱いにしない)
- ルールごとにユニットテスト必須(合成データで発火/非発火の両ケース)

## 3. generate_insight.py — 第2段階:所見文生成

- **入力**:stats.json のみ(raw回答全文は渡さない)
- **モデル**:Anthropic API(Sonnetクラス、環境変数で上書き可)、週1回のみ実行
- **プロンプト要件**:
  - config/playbook.md(運用プレイブックの内容を配置。リポジトリに含める)を
    システム指示に同梱し、発火ルールに対応するP-パターンの「原因と改善策」を参照させる
  - **stats.jsonにない数値・事実を書くことを禁止**(禁止事項として明示)
  - 出力フォーマット(Markdown、この構成に固定):
    1. 今週のサマリ(3行以内)
    2. 数値ハイライト(mention_rate 3系列・SoV首位・KGI週計:前週比付き)
    3. 発火パターンと推奨アクション(rule_idごとに:状態→原因仮説→アクション、
       アクションは「本田さんが承認/却下できる具体的な形」で最大3件)
    4. ウォッチ項目(発火はしていないが変化の兆しがあるもの、最大3件)
    5. 判定不能・データ不足の明示
- 出力の文字数上限:2,000字

## 4. 配信と保存

- **Slack**:毎週月曜 08:30 JST に既存Webhookへ投稿(週次レポート用に
  セクション整形。冒頭に「LLMO週次所見 YYYY-MM-DD」)
- **Sheets**:新タブ `weekly_reports` に保存(冪等)
  | date | stats_json | report_md |
- stats.jsonはdata/reports/YYYY-MM-DD.json としてもcommit(監査用)

## 5. 実行基盤

- weekly.yml を拡張(既存のAhrefs週次の後段に rules_engine → generate_insight →
  配信を追加)。スケジュールを月曜08:30 JSTに変更してよい(Ahrefs取得も同時刻で問題ない)
- workflow_dispatch で任意日付(--date)のレポートを再生成できること
- generate_insight の失敗時:stats.jsonの数値サマリだけでもSlackに送る
  (LLM障害でレポートゼロにしない)

## 6. Definition of Done

1. 全ルールのユニットテスト合格(発火/非発火/insufficient_data)
2. workflow_dispatch実行でSlackに週次所見が届き、weekly_reportsタブに保存される
3. 所見文中の数値がstats.jsonと一致している(スポットチェックで検証)
4. LLM呼び出し失敗をシミュレートしてもフォールバック配信される
5. README更新:Phase 2の構成図・週次運用フロー・コスト追記
   (想定:週1回のSonnet呼び出しで月100円未満)

## 7. 実装時の判断ルール

- 新規有料サービス導入禁止。ルール閾値(3日連続・4週連続・+0.10等)は
  config/rules_thresholds.yaml に外出しし、コード変更なしで調整可能にする
- 本指示書のルール定義・出力フォーマットは承認済み。変更が必要な場合は
  実装を止めて報告する
