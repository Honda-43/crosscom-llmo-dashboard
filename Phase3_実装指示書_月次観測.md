# Phase 3 実装指示書(第1弾)— 月次観測(BOFU・購買直前面)の追加

対象リポジトリ:crosscom-llmo-dashboard
目的:現行の日次観測7本はMOFU(検討段階)中心で、BOFU(購買直前:社名指名・
競合比較)が空白であることが判明した(LANY社フレームへの写像で特定)。
この空白を月次観測12本で埋める。日次観測・既存スキーマは一切変更しない。

制約(最重要):Gemini無料枠は1日20リクエスト/モデル。月次実行日は
日次7本+月次12本=19本で枠内に収める。月次プールを13本以上に増やす
場合は実行を2日に分割する設計とする(第1弾では分割不要)。

---

## 1. config/prompts_monthly.yaml 新設

| 項目 | 内容 |
|------|------|
| id | M-1〜M-12(添付xlsx「月次観測プール_第1弾」の採用12本) |
| category | bofu_single / bofu_compare / mofu_suppl |
| prompt | xlsxの観測プロンプト全文のとおり |
| target_brand | 比較型は競合名を記録(テクノデジタルコンサルティング等) |
| active | true |

プロンプト全文は添付xlsx(クロスコム_月次観測プール設計_v1.xlsx)の
M-1〜M-12を一字一句そのまま使用。第2弾候補M-13〜16はactive: falseで
先に定義だけ入れる。

## 2. run_monthly.py 新設

- 実行:毎月第1火曜 07:30 JST(日次7:00の後・同日実行で枠19/20)
  +workflow_dispatch
- 収集:既存collect_llm(リトライ・掃き直し・欠測通知を含む)を流用、
  2モデル(gemini/claude)
- 抽出:既存extract.pyをそのまま流用(§4スキーマ不変。比較の勝敗判定
  などの新項目は追加しない——既存のmention/rank/negative/kbf/citationsで
  観測する)
- 保存:シートタブ `monthly_observations` 新設(llm_observationsと同じ
  カラム+category列)。**日次のllm_observations・daily_summaryには
  混ぜない**(言及率等の日次指標を汚染しないため)
- 回答全文はdata/raw/monthly/YYYY-MM-DD/に保存

## 3. 月次サマリ通知(Slack)

実行完了後に1回投稿:
- 1行目:📅 LLMO月次観測 | YYYY-MM
- BOFU単体6本:言及の有無・ネガ検知・同名他社との混同の有無
- BOFU比較3本:自社と競合のどちらに言及が偏ったか(mention・rank・
  kbf_tagsから機械集計できる範囲で。判定できない場合は「要目視」と
  正直に書く)
- MOFU補完3本:言及有無と順位
- 末尾:回答全文の場所(シートリンク)

## 4. 観測範囲の注記(現状把握レポートの誠実性担保)

- 週次所見の§5(判定不能・データ不足)の固定文言に1行追加:
  「日次観測は検討段階(MOFU)中心であり、購買直前(社名指名・競合比較)の
  面は月次観測を参照」
- アプリR4獲得マップとLookerの使い方ページ用に、lk_verdictsではなく
  R4のキャプション文字列に同趣旨の注記を追加

## 5. Definition of Done

1. workflow_dispatchで初回実行し、monthly_observationsに24行
   (12本×2モデル)が入る
2. 月次Slackサマリが投稿される(--testで事前確認可能)
3. 日次実行・週次実行・既存テストに影響ゼロ(pytest全件pass)
4. Gemini実行数が日次+月次で20/日を超えない設計であることをテストで固定
   (activeな月次プロンプト数+7 <= 20 を検査)
5. README更新(月次観測の目的・LANYフレームとの対応・第2弾の追加手順)

## 6. 判断ルール

- 新規有料サービス禁止。抽出コストはHaiku級24回/月で数円
- 比較型の回答でクロスコムが同名他社と混同されていた場合は
  negative扱いにせず、monthly_observationsのnotes相当に記録し
  月次サマリで報告(エンティティ混同は別問題として扱う)
- 判断に迷う点は実装を止めて報告
