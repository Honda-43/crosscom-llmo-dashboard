# Phase 4 実装指示書 — ローカル分析アプリ(Streamlit)

対象リポジトリ:crosscom-llmo-dashboard
目的:案cの「深掘り分析UI」側。日常のグラフ確認はLooker Studio(別途手動設定)、
本アプリは回答全文・差分・所見まで一画面で追える分析環境をローカルに作る。
完全クローズド(ローカル起動のみ)・新規有料サービス禁止。

既存の§2プロンプト・§4抽出スキーマ・既存タブのスキーマは変更禁止。
実行系(daily/weekly)のコードには影響を与えないこと(読み取り専用アプリ)。

---

## 1. 技術構成

- Streamlit(app/ ディレクトリ配下、既存srcの読み取りロジックを再利用可)
- データソース:
  - Google Sheets(既存サービスアカウントで読み取り。認証JSONはローカルの
    credentials/service_account.json を参照。.gitignore必須)
  - data/raw/(回答全文。起動時にgit pullを促す)
- キャッシュ:st.cache_data(TTL 10分)でSheets APIコールを節約
- 起動:リポジトリ直下の run_dashboard.bat(Windows用:git pull → venv有効化 →
  streamlit run)。初回セットアップ用 setup_dashboard.bat(venv作成+pip install)も用意

## 2. 画面構成(5ページ)

### P1|概況
- 上段スコアカード:mention_rate all/A/B(直近7日平均+前週比矢印)、
  SoV首位エンティティ、negative_flag直近7日件数、AIセッション・指名クリック週計
  (noise_zone該当時はその旨表示)
- 下段:mention_rate 3系列の全期間推移(7日移動平均線付き折れ線)

### P2|SoV分析
- フィルタ:pillar(all/A/B)、期間
- エンティティ別シェア推移(上位N社の折れ線、クロスコムを強調色で固定表示)
- 当期間の出現回数ランキング(前期間比の増減付き)

### P3|プロンプト詳細
- prompt_id×modelを選択 → mention/rankの日次推移チャート
- kbf_tagsの出現頻度、cited_crosscom_urlsの期間内出現一覧
- 同プロンプトのcompetitors_mentioned集計

### P4|回答ビューア・差分
- 日付×prompt_id×modelで回答全文(data/raw)を表示
- 2つの日付を選んで回答全文のdiff表示(追加行/削除行のハイライト)
- 同日のchangesタブの該当行を併記

### P5|週次所見
- weekly_reportsタブの一覧と本文(Markdownレンダリング)
- 対応するstats.json(data/reports/)の主要数値を折りたたみで表示

## 3. 非機能要件

- 認証JSONが無い場合:Sheets系ページはエラーにせず案内文を表示、
  data/rawベースのページ(P4)は動作すること
- Sheets読み取りはタブごとに1回+キャッシュ。日次実行のAPIクォータに影響を
  与えない設計
- 依存関係はrequirements-dashboard.txtに分離(実行系のrequirements.txtに
  streamlitを混ぜない)

## 4. Definition of Done

1. setup_dashboard.bat → run_dashboard.bat の2ステップでブラウザにアプリが開く
2. 5ページすべてが実データで表示される(スクリーンショットを要約に添付)
3. 認証JSON欠如時の劣化動作が仕様どおり
4. README更新:セットアップ手順(サービスアカウントJSONの配置場所含む)

## 5. 実装時の判断ルール

- チャートライブラリ等の選択は自由(Streamlit標準+plotly推奨)
- 画面の細部デザインはClaude Codeの判断でよい。ページ構成・表示項目は
  承認済みのため変更しない。変更が必要な場合は実装を止めて報告する
