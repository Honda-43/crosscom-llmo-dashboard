# Phase 6 実装指示書 — Looker Studio統合(表示用データ層の全出力)

対象リポジトリ:crosscom-llmo-dashboard
目的:日常の閲覧をLooker Studioに一本化する。Lookerはレイアウトを
API構築できないため、**計算・判定・整形はすべてパイプライン側で行い、
Lookerは「シートのタブを置くだけ」で8面相当が組める状態**にする。
ローカルアプリは廃止しないが、回答差分の予備閲覧用に格下げする。

既存の§2プロンプト・§4抽出スキーマ・既存タブのスキーマは変更禁止。

---

## 1. 出力する表示用タブ(すべて日次実行で冪等更新)

接頭辞 `lk_` でLooker専用タブを明示する。既存の board_daily / citation_gap /
action_log はそのまま使う(変更最小)。

### lk_verdicts(判定欄)
| date | face | face_name | verdict_text |
- faceはR1〜R8、face_nameは日本語名(全体サマリ等)
- verdict_textは既存のverdicts.py(テンプレート生成)の出力そのまま
- 最新日のみでなく日次追記(判定の履歴が残る)

### lk_heatgrid(獲得マップ)
| date | prompt_id | prompt_name | model | days_mentioned_7d | cell_label |
- prompt_nameは「A-1 導入支援」等の日本語短縮名(config/prompts.yamlのcep先頭)
- cell_labelは「5/7」形式
- 最新日のスナップショットを日次で追記(dateでフィルタして最新を表示する設計)

### lk_scatter(競合ポジション)
| date | entity | share_28d | rank_median | rank_source | size_7d | is_crosscom | quadrant |
- rank_sourceは「実順位」(自社)/「シェア順位による代理値」(競合)
- quadrantは「高シェア×上位」等の4値(Looker側で計算させない)
- 上位10社+クロスコム、日次追記

### lk_sov_trend(言及シェア推移)
| date | entity | share_7d | is_crosscom |
- 7日移動平均済み。上位5社+クロスコムのみ(Lookerの線が増えすぎないよう
  パイプライン側で絞る)

### lk_negative(ネガ検知カレンダー)
| date | model | detected | note |
- detectedは1/0。noteは検知時の種別要約(20字以内・既存のSlack用要約を流用)

### lk_events(重要な変化)
| date | event_type | event_name | place | detail | playbook_ref |
- material eventのみ(既存の抽出ロジック流用)。event_nameは日本語
  (言及獲得/言及消失/引用喪失/競合上位入り/ネガ検知)

### lk_actions(アクションボード表示用)
| action_id | priority | content | target_display | rule_id | status | proposed | executed | deadline | days_to_deadline |
- action_logの表示用ミラー(値の日本語変換・期限までの日数計算済み)。
  元のaction_logタブは従来どおり本田さんの編集用として不変

### lk_answers(回答全文の閲覧用)
| date | prompt_id | model | mention | rank | answer_text |
- 直近14日分のみ(セル上限対策で answer_text は40,000字で切り詰め)。
  差分表示はLookerでは不可のため対象外(ローカルアプリに残す)

### board_daily(既存・拡張)
- 既存カラムに verdict_r1(R1の判定文) を追加(サマリ画面に判定を出すため)

## 2. 実行基盤

- run_daily.py の末尾フェーズとして lk_* 一式の書き出しを追加
  (すべて読み込み済みデータから構成し、Sheets読み取りの追加はしない。
  書き込みはバッチ化してAPIコールを最小化)
- 初回はバックフィル:llm_observations/sov_daily等の全履歴から
  lk_sov_trend / lk_negative / lk_verdicts(算出可能な分)を過去分生成する
  workflow_dispatch対応スクリプト scripts/backfill_looker.py を用意
- 週次(run_weekly.py)は citation_gap 更新後に lk_scatter の再集計も行う

## 3. ローカルアプリの扱い

- 削除しない。README冒頭の位置づけを「日常閲覧はLooker Studio。
  本アプリは回答差分の確認用」と更新
- アプリ側の変更は不要(工数をかけない)

## 4. Definition of Done

1. workflow_dispatchでdailyを実行すると lk_* 全タブが生成され、
   実データが入っている(件数サマリを報告)
2. backfill_looker.py で lk_sov_trend / lk_negative が全期間分入る
3. 2回実行しても重複しない
4. 各タブの先頭5行のサンプルを完了報告に含める(Looker組み立て時の
   フィールド対応確認用)
5. README更新(タブ一覧・Looker側で使う面との対応表)
6. pytest既存全件+lk_出力のテスト(スキーマ・冪等性)pass

## 5. 実装時の判断ルール

- 新規有料サービス禁止。表示文言は日本語(製品名・識別コードを除く)
- Lookerでの見せ方に迷う整形(例:quadrantの文言)は本指示書の指定を優先
- 判断に迷う点は実装を止めて報告
