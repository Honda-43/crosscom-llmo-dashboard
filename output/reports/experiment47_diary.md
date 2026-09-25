# LLMO効果測定 実験日誌（47本）

観測の結果を後から読むとき、「その週に何が起きていたか」を思い出せないと、
数字の増減を処置の効果として読んでしまう。ここは**処置以外に起きたこと**を残す場所。

- 対象：`config/prompts_experiment.csv` の47本
- 観測：`llm_experiment` タブ（日次・claude / gemini）。ワークフローは `.github/workflows/experiment.yml`
- 別系統の観測：`experiment_2x2/results/*.csv`（引用プローブ・claude のみ）
- 欠測の理由別記録：`data/experiment_journal.csv`（quota=枠切れ / unavailable=503 の一時的な混雑。1行1件・自動追記）
- 本文の変化の監視：`experiment_2x2/drift_check.py`（毎週月曜）

各行の「確かめ方」は、書いた内容を何で裏取りしたか。裏が取れていないものはそう書く。

---

## 2026-09-11 〜 09-16／publish_followup が47本のうち17本に逆リンクを追記した

新規記事の公開にともない、`publish_followup` が既存記事の本文へ
「その新規記事へのリンク1文」を自動で足した。対象47本のうち **17本・のべ24本のリンク**。
記事別の本数・張り元・追記文の全文は
`crosscom-seo-agent/output/reports/bunGL_experiment48_append_record_20260917.md` にある。

組ごとの本数（48本版の振り分けでの数。9/28 の割付では層として使い直す）：

| 組 | 追記を受けた記事 | 逆リンク本数 |
|---|---|---|
| ①対照 | 4本 | 4本 |
| ②FAQのみ | 4本 | 5本 |
| ③リードのみ | 3本 | 4本 |
| ④両方 | 6本 | 11本 |

最初の追記 2026-09-11 17:46:14、最後の追記 2026-09-16 16:02:06（いずれもJST）。

**なぜ残すか**：逆リンクが増えること自体が引用されやすさに効く可能性がある。
17本が組に固まると、処置の効果と見分けがつかなくなる。
9/28 の割付（`allocate_47.py` の条件 b）で、17本を各組4〜5本に散らす。

確かめ方：WP REST（GET）で47本の本文と `modified` を取得し、
`publish_followup` の FOLLOWUPS の `link_marker` が本文にあるかを1件ずつ突き合わせた。

---

## 2026-09-15 〜 09-16／ビフォー観測の期間中に3本へ追記が入った

ビフォー観測が始まった後に、次の3本が追記を受けた。

| url | 追記日時(JST) | 逆リンク本数 | 張り元 |
|---|---|---|---|
| https://cross-com.jp/revops-guide/ | 2026-09-15 16:56:54 | 2 | 7136 churn-signal / 7177 role-design |
| https://cross-com.jp/agentforce-observability/ | 2026-09-15 16:58:38 | 2 | 7139 effect-measurement / 7183 sales-meeting |
| https://cross-com.jp/hyper-personalization/ | 2026-09-15 17:02:20 | 3 | 7161 behavior-data / 7168 cs-handback / 7189 lead-follow |

**この3本は、ビフォー期間の中で本文が変わっている。**
9/15 の観測と 9/16 以降の観測が、同じ本文を見ていない。

**決定（2026-09-18・効果測定チャット）：この3本は 9/17 以降の観測のみをビフォーに使う。**
他の44本は 9/15 からの観測をそのまま使う。

追記そのものは**戻さない**。戻すのも編集にあたり、戻した時点でさらにもう一段の
変化が入る。入ってしまったものは、記録して層として扱う。

確かめ方：上と同じ。追記日時は WP の `modified` と
`publish_followup` が残すバックアップファイルの更新時刻が一致している。

---

## 2026-09-17 23:30 〜 09-18／引用プローブのビフォー観測（experiment_2x2）

`llmo_probe.py` で47本＋`agentforce-pricing` の計48本 × claude × 3回 = 144行を取得。
`experiment_2x2/results/2026-09-17.csv`。

- 9/17 23:30〜23:59 に69行。**バックグラウンドのプロセスが落ちて中断**（1件はAPIのタイムアウト）
- 残り75行は 9/18 に `resume_probe.py` で取得し、同じファイルへ追記
- `run_date` は 2026-09-17 のまま。ビフォー観測を1点として扱うため
- モデルは `claude-sonnet-5` に固定（`llmo_probe.py` の既定値を変更）

**取得日が2日にまたがっている。** 9/18 に取った75行は、9/17 に取った69行より
1日ぶん後の検索結果を見ている。厳密には同じ時点の観測ではない。

確かめ方：`results/2026-09-17.csv` の行数と `resume_run.log`。

---

## 2026-09-18／publish_followup にプール除外を実装（以後、自動の追記は止まる）

`publish_followup` が `experiment_2x2/targets.csv` の48本（＝47本＋`agentforce-pricing`）を
読み、未実施の逆リンク追記をスキップして pending に積むようにした。

- 除外期限 **2026-12-31**。翌日から自動で通常どおり追記する
- `targets.csv` を読めないときは追記しない（fail closed）
- すでに入った追記は戻さない
- 先送り分は `output/reports/pending_followup_after_experiment.md` に積む
- crosscom-seo-agent のコミット `034101d`

着手は 9/17 深夜、コミットは 9/18。

**最後の追記（09-16 16:02:06）以降、47本は1本も更新されていない**ことを
WP の `modified` で確認済み（0本）。ここから先は自動の追記は入らない。

ただし止まるのは**把握している経路だけ**。人手の修正・プラグインの出力変化・
テーマ更新は止められないので、`drift_check.py` で毎週確かめる。

---

## 2026-09-18／本文の変化を毎週見る仕組みを作り、基準を取った

`experiment_2x2/drift_check.py`。47本の公開ページから `<article>` の中身を取り、
正規化して sha256 を保存する。翌週以降、変化があれば
`output/reports/experiment47_drift_YYYYMMDD.md` に記事URLと差分を出す。

- 基準：2026-09-18 取得、47本すべて成功（失敗0）
- 「関連記事」ブロックは表示のたびに中身が入れ替わるため、本文の終わりで切っている。
  含めると毎週「変化あり」になり、本物の変化が埋もれる
- 同じページを2回取ってハッシュが一致することを3本で確認（誤検知なし）。
  1行変えれば差分が出ることも確認

以後、毎週月曜に実行する。

---

## 観測の開始時刻について（記録の食い違い）

「ビフォー観測開始 9/15 08:00」とあるが、実測は次のとおり。

- `.github/workflows/experiment.yml` の cron は `0 23 * * *` UTC = **08:00 JST**（予定時刻）
- `llm_experiment` タブの最古の行は **2026-09-15T01:10:00Z = 10:10 JST**（実際の1行目）

予定は 08:00、実際に最初の行が入ったのは 10:10。初回は手動実行か遅延とみられる。
基準値を日単位で見るぶんには影響しないが、時刻まで遡って読むときは 10:10 を使う。

確かめ方：ワークフローの cron 定義と、`llm_experiment` の `timestamp` 列の最小値。

---

## 2026-09-22／鮮度更新の裁定：3本に誤り訂正が入る予定（9/29〜30・処置反映と同日）

月次の鮮度更新（管BK）の裁定により、47本のうち次の3本へ**誤り訂正**を入れる。
入れる日は **9/29〜30、2x2の処置反映と同じ日**。

| url | 47本の番号 | 条件 |
|---|---|---|
| https://cross-com.jp/agentforce-coworker/ | E37 | 確定 |
| https://cross-com.jp/agentforce-features/ | E12 | 確定 |
| https://cross-com.jp/agentforce-vibes/ | E11 | **価格の食い違いが確定したときのみ** |

- 訂正の範囲：**本文の数文の差し替えのみ**。リード文とFAQは変えない
  （リード文・FAQは処置そのものなので、訂正で触ると処置と区別がつかなくなる）
- 処置反映と同じ日に入れるのは、変化の時点を1点にまとめるため。
  別の日に入れると、アフター観測の途中でもう一段の変化が入る

**なぜ残すか**：この3本はアフター期間の本文に「処置」と「訂正」の両方が乗る。
訂正が引用に効いた分を処置の効果として読まないよう、所属組と差し替え文を残す。

### 9/28 追記予定：3本の所属組

振り分け確定後、dashboard 側の `allocation_v1` から転記する。
（参考：`experiment_2x2/targets.csv` は 9/17 の48本版で、coworker＝①対照、
features＝②FAQのみ、vibes＝③リードのみ。9/28 の割付で変わりうるので、これは使わない）

| url | 所属組（allocation_v1） |
|---|---|
| agentforce-coworker | （9/28 記入） |
| agentforce-features | （9/28 記入） |
| agentforce-vibes | （9/28 記入） |

### 9/29〜30 追記予定：差し替え前後の文

| url | 差し替え前 | 差し替え後 | 適用日時(JST) |
|---|---|---|---|
| （記入） | | | |

vibes を見送った場合は、見送ったことと理由をここに書く。

### 週次ドリフト検知での読み方

`drift_check.py` でこの3本が「変化あり」と出た場合は、上の差し替え前後の文と照合し、
一致すれば drift レポートに「**想定内の変更（9/22 裁定の誤り訂正）**」と明記する。
記録にない差分が混じっていれば、想定外として別に扱う。

確かめ方：裁定の内容は依頼文（9/22）による。3本が47本に含まれることは
`config/prompts_experiment.csv`（E11・E12・E37）で確認した。所属組・差し替え文は未記入。

---

## 2026-09-22（続き）／agentforce-coworker を実験から外し、編集禁止を49本へ。9/29〜30 に日付付きの例外

上の項の裁定を受けて、編集禁止リストと適用の経路を次のとおり変えた。

**1. coworker（post 7003）を実験から外した**
- `experiment_2x2/targets.csv` から coworker の行を削除。**49本**になった
  （統計の対象46本＋`agentforce-pricing`＋ピラー2本）。ファイル先頭の # 注記も49本に更新
- coworker は「**実験除外・編集可**」。publish_followup では `EXPERIMENT_RELEASED` に明示し、
  `prompts_experiment.csv` に残っていても突き合わせで落とさない
  （黙って消えたのか、裁定で外したのかを区別するため）
- 上の項の表・「3本込み／3本抜き」のうち、coworker の訂正は**実験の外の編集**になる。
  適用日を 9/29〜30 に合わせる必要は無くなった

**2. publish_followup の除外も49本**
- targets.csv を読むので自動で49本になる。ドライランで確認：
  「統計の対象 46本 ⊂ 編集禁止 49本（整合）／実験除外：agentforce-coworker」
- 逆リンクの追記は、下の例外の対象に**しない**（処置ではないため。従来どおり 2027-01-01 以降）

**3. 9/29〜30 の日付付きの例外（apply_gate）**
- 期間：**2026-09-29 〜 2026-09-30**（JST・日付で判定）
- 通すもの：allocation_v1 の**処置群（②③④）**と `agentforce-vibes`
- 処置群は `output/reports/experiment47_allocation_v1_20260928.md` の割付表から読む。
  **読めなければ処置群は通さない**（fail-closed。vibes だけが通る）
- 10/1 以降は再び全面禁止
- 定義は seo-agent の `publish_followup.py` の `EXPERIMENT_WINDOWS`（apply_gate はそれを読むだけ）

確かめ方：apply_gate のセルフテスト 28ケース NG0、publish_followup のセルフテスト NG0、
検出器テスト 54件 NG0。実際の一覧での判定（2026-09-22 時点・割付表はまだ無い）：
coworker 9/22 通る／vibes 9/22 落ちる／vibes 9/29 通る／features 9/29 落ちる（割付表が無いため）／
vibes 10/1 落ちる／agentforce-guide 9/29 落ちる。

**未決（効果測定チャットで決める）**
- `config/prompts_experiment.csv` と `allocate_47.py`（`assert len(arts) == 47`・SIZES 12/12/12/11・
  CORRECTION_SLUGS）はまだ47本のまま。46本で割り付けるなら 9/28 までに直す必要がある
- features が割付で①対照になった場合、例外では通らない（処置群と vibes だけが対象）

---

## 2026-09-22／プールを46本に更新（E37 除外）・E12 は残留・1週目の集計

**E37（agentforce-coworker）をプールから除外。統計は46本**
- 理由：鮮度更新の訂正が**見出し・FAQに及ぶ**ため。FAQ は処置そのもので、訂正と処置を切り分けられない
- `config/prompts_experiment.csv` から E37 の行だけを削除（他の46行は元のまま。番号は振り直さない）
- 9/23 以降の実験観測（dashboard の Gemini・Claude）は46本。Gemini の巡回の輪も46本になる
- 9/15〜9/22 の llm_experiment に残る E37 の行は消さない。週次集計・割付・判定では数えない
- 週の観測本数の目標は 46本×週2回 = **92本**（47本のときは94本）

**E12（agentforce-features）はプールに残留・訂正は見送り**
- 理由：引用実績が無い（1週目の集計で Gemini・Claude とも cited_article=0）
- 残留するので、9/28 の割付の対象に入る。条件 f（訂正対象の分散）の対象からは外した

**条件 f の対象は agentforce-vibes のみ**
- 判定は「vibes込み／vibes抜き」の両方を出す（`experiment_2x2/summarize.py`）
- 割付は 46本・4組 12/12/11/11（`experiment_2x2/allocate_47.py`）。9/22 時点のデータでの
  ドライランは条件 a〜f をすべて満たすシードが見つかることを確認済み（本番は 9/28 に 9/15〜9/27 で引く）

**1週目（9/15〜9/21）の集計**（`output/reports/experiment47_week1_20260922.md`。E37 を含む47本で集計）
- cited_article の率：**Gemini 17.8%（13/73）／Claude 3.2%（3/94）**
- 記事URLが1回でも出た記事：**8本**（E37 を含む。E37 を除くと7本）
- 枠切れ（PerDay）の欠測：10件（すべて 9/19。日次の再試行が枠を使ったため。f6c2a0b で修正済み）

**観測・判定のスクリプトは targets.csv を読まない**
- `llmo_probe.py`・`resume_probe.py` は `config/prompts_experiment.csv`（46本）を読む。
  組は割付の結果 `experiment_2x2/allocation_v1.csv`（9/28 に `allocate_47.py` が書く）から引く
- **質問文が変わる**：targets.csv の `query`（KWマスターの主KWから作った質問）から、
  prompts_experiment.csv の `prompt`（dashboard の実験と同じ文）になる。46本すべてで文が異なる。
  9/17 の引用プローブ（144行）は旧い質問文で取ったもので、新しい質問文のアフターとは比べられない
- 週次集計は毎週月曜に自動生成（`src/experiment_weekly.py`・weekly.yml。
  `output/reports/experiment47_weekN_YYYYMMDD.md`。前の週の月〜日。cited_domain の率を追加し、
  mentioned は参考欄）

**追記（同日）**：上の「未決」1点目は解消済み。`eab2dd0` で `prompts_experiment.csv` から E37 を外して46本、
`allocate_47.py` も46本前提（12/12/11/11・訂正対象は vibes のみ）になった。
apply_gate が読む割付表の書式・場所（`output/reports/experiment47_allocation_v1_20260928.md`）は変わっていない。
試しに割付表を scratchpad へ出して読ませたところ、46行・処置群34本・対照12本を読み、
9/29 に処置群と vibes を通し、対照群とピラーを落とし、10/1 はすべて落とした。
2点目（features が①対照なら通らない）は、訂正対象から features が外れたため問題でなくなった。

## 2026-09-22 15:38／E37（agentforce-coworker・post 7003）の誤り訂正を適用（管BO・管BP）

**処置ではない**（E37 は同日プールから除外済み）。鮮度更新の裁定による誤り訂正。記事制作の便II で適用。
- 変えたのは4か所だけ（WP の本文差分を機械で確認：4か所の範囲の外の変化 0）
  1. H3：「チャネル③順次拡大が予定される外部チャットから呼び出す」→「チャネル③TeamsやClaudeなど外部のチャットから呼び出す」
  2. 同H3の本文 第1段落：Teams・ChatGPT・Claude・デスクトップアプリへの対応は「順次予定」→ Salesforce の製品ページで Teams・Claude・ChatGPT・モバイルの中でも使えると案内（2026年9月時点）＋出典行1本
  3. 同H3の本文 第2段落：「対応時期が明示されていない…すでに使える2つのチャネルで組み立てる」→ 接続が自社の組織で有効かを確かめてから広げる
  4. FAQ 質問③の回答の後半2文：「順次予定・時期は示されていない」→「製品ページで案内（2026年9月時点）」
- 目次は見出しから自動生成のため追従（表示ページで旧見出し0回・新見出し3回＝目次2＋H3）。7003 は FAQ ブロック化されておらず FAQPage は無い
- していないこと：リード文の追加・FAQブロック化（型A化）・残り46本への内部リンク追加・publish_followup の逆リンク追記（7003 は個別に止めてある）
- 一次情報：https://www.salesforce.com/agentforce/coworker/（09-22 取得）「Agentforce Coworker lives within the apps your employees use every day, like Salesforce, Slack, Microsoft Teams, Claude, ChatGPT, and mobile.」
- 差し替え文の全文（変更前後）：crosscom-seo-agent/output/reports/bunII_7003_applied_20260922.md
- 完了報告 CSV：crosscom-seo-agent/output/reports/experiment47_completion_report.csv（group=除外・treatment 0/0）

**訂正前の引用（ビフォー観測・判定には使わない）**
- 質問（E37）：「Agentforce Coworkerとは何？営業がどんな場面で使える？」
- Gemini 9/16・9/21、Claude 9/17・9/21 の4回すべて cited_article=1（記事URLごと引用）
- ★E37 は prompts_experiment.csv から外れたため、このままでは訂正後の引用を追えない（提案は記事制作の便II 報告 §3）

---

## 2026-09-23／E37 は watch で観測継続・features の訂正を了承・転送URLの確認

**2026-09-22 15:38 E37（agentforce-coworker）の完全訂正（実験外）**
- 詳細は上の「2026-09-22 15:38」の項。見出し・FAQに及ぶ訂正で、処置ではない
- E37 はプール（統計の46本）から外したまま、**観測は続ける**（`config/prompts_watch.csv`）。
  llm_experiment では `experiment_flag=watch`。割付・判定（`summarize.py`）・週次集計・週の観測目標には入らない
- 観測の巡回は プール46本 + watch1本 = 47本になった（9/24 以降の割当から）。Claude は 月・木 に47本

**2026-09-23 features（E12）の本文1文の訂正を了承（適用は 9/29〜30・処置反映と同日）**
- 条件 f（訂正対象を各組に最大1本）の対象を **agentforce-vibes と agentforce-features の2本** にした
- 判定は「2本込み／2本抜き」の両方を出す（`experiment_2x2/summarize.py`）
- **要確認（seo-agent 側）**：9/29〜30 の apply_gate の例外は「処置群（②③④）と vibes」だけを通す。
  9/28 の割付で features が①対照になると、了承した訂正が例外で通らない。
  `publish_followup.py` の `EXPERIMENT_WINDOWS` に features を足す必要がある

**Gemini の転送URLの解決を確認（`output/reports/experiment47_redirect_check_20260923.md`）**
- 9/15〜9/22 の Gemini 99行（引用のある84行）、転送URL 1,169件のうち、解決に失敗したのは **6件（6行）**。
  タイムアウトは0件。5件は転送先サイトの TLS エラー、1件は当時の一時的な失敗（9/23 は解決できた）
- 失敗6件の行き先はすべて外部サイト。**cited_article・cited_domain の判定への影響は0件**。
  記録された cited_article と、解決後URLから計算し直した値の不一致も0件
- 9/23 から、転送をたどれないときは `Location` ヘッダーで行き先を読む（TLS エラーの5件はこれで解決できる）
- 9/23 から llm_experiment に `raw_cited_urls`（生の引用元URL）と `experiment_flag` の列を足した。
  それより前の行の生URLは `raw_file` の JSON にある

---

## 2026-09-25／ビフォー期間中の追記9本を受けて、くじ引きの条件と基準値を更新

**何が起きていたか**
- 9/15〜9/16 に `publish_followup` が、統計46本のうち**9本**へ逆リンクを追記した
  （リンク1本＋約100字。ほかにピラー `agentic-crm` にも入った）。
  **ビフォー観測の途中で本文が変わった9本**で、9/11〜9/14 の8本と合わせて17本が追記を受けている
- 9本：revops-guide / agentforce-observability / hyper-personalization / salesforce-data-360 /
  buyer-enablement（9/15）、agentforce-subagents / agentforce-employee-agent /
  agentforce-use-cases / agentforce-testing-center（9/16）

**くじ引きの条件（9/28 実行）**
| 条件 | 内容 | 変更 |
|---|---|---|
| a | 各組 11〜12本（46本なので 12/12/11/11） | そのまま |
| b | 9/11〜9/16 に追記を受けた記事（層の表の全件・現在17本）が組間で均等（最大差1） | 「17本が各組4〜5本」から一般化 |
| c | 引用あり（9/15〜9/27 に cited_article=1 が1回以上）が組間で最大差1 | そのまま |
| d | 2026-09 公開・2026-07 公開がそれぞれ組間で最大差1（d-1・d-2） | そのまま |
| e | **9/15〜9/16 に追記を受けた9本が各組 2〜3本（最大差1）** | 新設 |
| f | agentforce-vibes・agentforce-features が各組に最大1本 | そのまま |

- b・e の母数は `experiment_2x2/strata_backlink17.csv` の `appended_at` から自動で決まる。
  制作管制の「9/11〜9/16 の全追記の表」で作り直せば、条件の中身もそのまま追従する

**ビフォー基準値（2026-09-25 確定）**
- **ビフォー基準値の扱いを確定。** 9/11〜9/14 の追記分はそのまま使用（条件 b で均等化）、
  9/15〜16 の追記9本は 9/17 以降のみ使用。**除外・補正はしない。**
  判定時に9本込み／抜きの感度分析を行う
- 9本は `pool.LATE_BASELINE_FROM`（2026-09-17）で自動的に切る（`summarize.py`）。
  9/15 の3本に適用していたルールを9本へ広げた
- 判定の出力は**感度分析の4通り**を1つの表に並べる（`summarize.py`）：
  両方込み / 9本抜き（9/15〜16 追記）/ 2本抜き（訂正対象）/ 両方抜き。
  4通りで結論が食い違う場合は、処置ではなく追記か訂正の影響として扱う

**介入ログ（`output/interventions.csv`）**
- I-09 を追加：9/15〜16 の逆リンク追記（touches_pool46=**yes**）
- I-04（sameAs 6→7・Yoast 組織設定・全ページ共通・9/20〜22・本田さん）を記入。プール46本の本文には触れない
- I-05（タイトル・メタディスクリプション改修。9/15 より前に完了、9/15 以降の変更0件）を記録のみで記入

**待ち**
- 制作管制の「9/11〜9/16 の全追記の表」。受け取り次第 `strata_backlink_YYYYMMDD.csv` に作り直し、
  前回の17本との差分（増えた記事・消えた記事）を報告する。`pool.strata_path()` が新しいファイルを自動で使う
