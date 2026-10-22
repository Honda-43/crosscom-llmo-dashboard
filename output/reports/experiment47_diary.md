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
| agentforce-coworker | 割付なし（9/22 にプールから除外・watch で観測継続） |
| agentforce-features | **③リードのみ**（E12・2026-09-28 記入） |
| agentforce-vibes | **④両方**（E11・2026-09-28 記入） |

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

**9/11〜9/16 の全件走査（2026-09-25 追記）**
- 全件走査で**48本の編集**が判明した（見出し型 A〜L の一括反映。公開50本・下書き28本、本文±100字程度）
- **9/11 の一括反映は全組一様**なので、組の差にはならない。**ベースラインの変更として織り込む**
  （介入ログ I-11。除外も補正もしない）
- **条件 b を「便GL の17本リスト」から「全件走査で 9/11〜9/16 にリンクが増えた記事」に切り替える**。
  母数は制作管制の `experiment_2x2/edits_20260911_0916.csv` から作る `strata_backlink_YYYYMMDD.csv`
- **条件 g を新設**：タイトル変更3本（agentforce-for-sales-sdr-sales-coach /
  agentic-ai-guide / agentic-crm-pipeline-stagnation-detection）は各組に最大1本。
  タイトルは引用のされ方を直接動かすので、組に固まると処置と分けられない
- タイトル変更の日時が 9/15〜16 と分かった記事は、9/17 以降のみ使用の対象（現在の9本）に加える
  （`pool.TITLE_CHANGE_DATES`。分かるまでは基準値の扱いを変えない）
- 介入ログに I-11（9/11 の一括反映）・I-12（9/11〜14 のリンク増）を追加。
  I-10 は seo-agent 側が足したものとしてそのまま残し、以後このファイルは dashboard 側だけが書く

**全編集一覧の取り込み仕様（2026-09-25 確定）**
- 制作管制が `crosscom-seo-agent/output/reports/edits_20260911_0916.csv` を作る（**期限 9/27 23:59**）。
  14列：slug / post_id / edited_at_jst / pool_class / edit_type / source / chars_delta /
  links_before / links_after / added_link_targets / removed_link_targets /
  title_changed / title_before / title_after
- 手順（`make_strata.py` が1コマンドで行う）:
  ```
  python experiment_2x2/make_strata.py --copy-from ../crosscom-seo-agent/output/reports/edits_20260911_0916.csv
  ```
  1. seo-agent 側のファイルは読むだけ。`experiment_2x2/edits_20260911_0916.csv` にコピーする
  2. 列名・列数・並び・型を検査し、**1つでも合わなければ何も書かずに止めて報告する**（推測で読まない）
  3. 「pool_class=統計46 かつ links_after > links_before の行を1行以上持つ記事」を抽出して
     `strata_backlink_YYYYMMDD.csv` を作り、17本との差分（増えた記事・消えた記事）を出す
  4. `title_changed=1` の `edited_at_jst` から `title_changes_YYYYMMDD.csv` を作る。
     9/15 以降の記事は条件 e と「9/17 以降のみ」の対象に自動で入る
  5. 条件 a〜g でドライランして結果を報告する
- 検査で止めるのは、列がずれたまま読むと層に入るはずの記事が静かに抜け落ち、
  条件 b が偏ったまま通ってしまうため
- **9/27 23:59 までに届かなかった場合**：条件 b は便GL の17本（`strata_backlink17.csv`）のまま
  9/28 のくじ引きを実行し、その旨をこの日誌に記録する

**edits CSV を取り込み（2026-09-25・17列）**
- **境目は観測開始時刻 2026-09-15 08:00 JST で判定する（JST・GMT の日付の境目は使わない）。**
  日付で切ると 9/15 01:34 の編集（agentforce-einstein-difference・agentforce-service-agent）まで
  巻き込むが、あの2本は観測が始まる前の編集で、ビフォーの1回目から新しい本文を見ている
- **リンクの判定は内部リンク**（`links_before` / `links_after`）。`links_*_all`（外部込み）は使わない
- 条件 b・e をこの基準で更新した：
  - 条件 b（リンクが増えた記事）: **17本 → 23本**。増えた6本は agentforce-agent-script /
    agentforce-einstein-difference / agentforce-mcp / agentforce-security-risk-design /
    agentforce-service-agent / agentforce-usecase-selection。消えた記事はなし
  - 条件 e（観測開始〜9/16 に変わった記事）: **9本（顔ぶれは変わらず）**。
    9/15 01:34 の2本は観測開始前なので入らない
  - タイトル変更3本はすべて 9/12〜9/14 で、**「9/17 以降のみ」の対象には入らない**
  - `edit_type=その他` かつ 統計46 かつ観測開始以降の行は **0行**
    （スキーマ追加・メタ変更は観測開始後に入っていない）
- **判定の p値は再ランダム化検定で出す（2026-09-25 決定）**：
  条件 a〜g の合格率が約 1/9,200 のため、判定の p値は**同じ条件を満たす割付の中で**計算する。
  **条件の追加は行わない。** フィッシャー正確検定は参考として並べる。
  プール（条件 a〜g を満たす割付 5,000通り・シード 20290101 から順・実際の割付は除く）は
  9/28 の割付が決まったあとに `rerandomize.py --build` で作り、
  `experiment_2x2/results/rerandomization_pool.csv` に保存して判定のたびに読み直す。
  感度分析の4通りそれぞれに同じ検定をかける
- 取り込んだファイル: `edits_20260911_0916.csv`（136行・49本）、生成物は
  `strata_backlink_20260925.csv` / `late_changes_20260925.csv` / `title_changes_20260925.csv`
- **I-09 の補足**：publish_followup の追記に**止めの実装が入ったのは 2026-09-18**。
  **9/17〜9/18 の追記なし**。edits CSV では観測開始後の逆リンク追記は 9/16 16:02
  （agentforce-testing-center）で終わり、9/17 以降の行は0件。
  ただし同ファイルの範囲は 9/11〜9/16 なので、それだけでは 9/17〜9/18 の不在は示せない。
  便GL の記録（9/17 作成・9/18 追記）にも 9/17・9/18 の追記行が無いことで裏を取った

---

## 2026-09-25／measurement_design のリード件数の記述を訂正（Sandbox 照会だった）

- `measurement_design_2026-09-14.md` のリード件数の記述（「Lead は全体で1件、最新の作成日は 2026-03-19」）が
  **Sandbox（JPN2S）照会だったため訂正**。Salesforce MCP の接続先が Sandbox に固定されていたことに
  当時気づいていなかった（制作管制報告・R-83）。元の文は取り消し線で残し、直後に訂正注記を入れた
- **実験の判定には使わない指標のため影響なし。** 問い合わせ・リード（L4）は LLMO実験の
  設計・判定・割付のどれにも入らない（判定は `llm_experiment` のみ）
- 確定版 `measurement_design_2026-09-17.md` にも同じ照会に基づく同じ記述があったため、同じ訂正を入れた
- `config/kgi.yaml` の `official`（Lead の項目定義から写した選択リストの API 値）は
  **接続先未確認**と明記した。コードはこの定義を読まない（読むのは GA4 の `supplementary.key_events` だけ）
- dashboard のコードから Salesforce へ接続する処理は無い（SOQL は文書に載せた手動照会用のみ）
- **訂正注記の文言を再訂正**（同日）。「流入自体が少ない」は原典に存在しない文言だったため削除し、
  原典の3つの原因のうち **3（照会組織の相違）で確定**、1（問い合わせが無かった）・2（フォーム送信が
  Lead を作れていない）は本番で確かめるまで未確定と明記した。09-17 確定版にも同じ訂正を適用
- **訂正注記を再々訂正**（同日）。確定したのは **原因3の後半（照会組織の相違）のみ**で、
  Sandbox を照会していたことで元の観測そのものが無効になったため、ほかの可能性
  （問い合わせが無かった／フォーム送信が Lead を作れていない／Lead が別の場所へ移っている）は
  すべて未確定と明記した。09-17 確定版は同文書の語（「照会先の組織が違う」）に合わせた
- **フォームの送信先が Supabase の自作フォームと判明**（制作管制 便JZ）。原因2の「retURL 不備」は
  Salesforce Web-to-Lead 前提のため、「**送信内容の書き込み先と本番 Lead への経路の確認**」に置き換えた。
  `config/kgi.yaml` の `official` と README の該当行に「取り出し元未確認（フォームの送信先は Supabase）」を明記
- **L4 は判定に使わないため実験への影響なし**（判定は `llm_experiment` のみ）

---

## 2026-09-26 14:46／E37（agentforce-coworker・post 7003）の権限セット名の差し替えを適用（便MC）

**処置ではない**（E37 はプールから除外済み・観測は watch で継続）。事実の誤りの訂正。記事制作の便MC で適用。
- 箇所：H2「Agentforce Coworkerを使い始める4ステップ」ステップ③の第2段落（1段落のみ・見出しは不変）
- 内容：他社（フロッグウェル）の検証記事由来の名称（「Ask Agentforce Setup」「Ask Agentforce」／「エージェンティックエンタープライズ検索ユーザー・管理者」）を、
  公式の記載へ差し替え。開発者ドキュメント「Agentforce Coworker Admin」と FAQ「Ask Agentforce Admin」を併記し、同じものかは断定しない
- 外部リンク +2（developer.salesforce.com／help.salesforce.com）。内部リンクの増減なし（新規リンク禁止47本の照合に掛からない）
- WP modified：2026-09-26T14:46:30（context=edit で再読一致・sync_check 乖離0）
- 判定には影響しない（E37 は統計の46本に入っていない）。引用の追跡のために適用日時を残す
- 変更前後の全文：crosscom-seo-agent/output/reports/bunMB_coworker_names.md

---

## 2026-09-26 17:37／E37（agentforce-coworker・post 7003）へ D-42（出典のインライン化）を適用（便MI・便MH §1）

**処置ではない**（E37 はプールから除外済み・観測は watch で継続）。出典の書き方の変更（D-42）と、欠けていた出典リンク1本の追加。
- 旧形式「※参考記事はこちら」6件を、主張文の中核語句へインライン化（URL は既存のまま）。参考行だけの段落1つを削除
- H2「Coworker導入でつまずく3つの落とし穴」のフロッグウェル由来の記述に、同じ出典のリンクを1本追加
- 本文に書かれていた target="_blank" 5件は、インライン化で本文から消えた（B-33 のフィルタが表示時に付ける）
- リンク 22→23（すべて外部。内部リンクの増減なし）／44,696→44,497字
- WP modified：2026-09-26T17:37 台（context=edit で再読一致・sync_check 乖離0・D-42 違反0）
- 判定には影響しない。引用の追跡のために適用日時を残す
- 変更の一覧：crosscom-seo-agent/output/reports/bunME_coworker_d42_plan.md

---

## 2026-09-26／agentforce-vibes の訂正を見送り（戦略管制塔の裁定）

- **vibes の本文訂正は見送り**（凍結明けへ）。9/29〜30 に訂正するのは
  **agentforce-features の1文のみ**になった
- `output/interventions.csv` の I-07 の description を「訂正2件（vibes・features）」→
  **「訂正1件（agentforce-features）」** に修正
- 判定の感度分析の3通り目を「2本抜き（訂正対象）」→ **「features 抜き（訂正対象）」** に変更。
  抜くのは `pool.APPLIED_CORRECTION_SLUGS`（features の1本）だけ。4通りは
  **両方込み／9本抜き／features 抜き／9本＋features 抜き**。再ランダム化検定も同じ4通りにかける
- **くじ引きの条件 f（vibes・features は各組最大1本）は変更しない**（`pool.CORRECTION_SLUGS` は2本のまま）。
  9/28 のシード探索は条件で決まるので、後から条件を動かすと引き直しの結果そのものが変わる。
  README にも「条件 f は vibes の訂正見送り後もシード探索の一貫性のため維持」と明記した

---

## 2026-09-28／本番のくじ引き（割付 v1 の確定）・ビフォー期間の揺れの幅

### 割付

- **採用シード：20270135**（開始 20260928 から 9,208 個目）。条件 a〜g をすべて満たした最初のシード
- 引用あり（条件 c）の判定：llm_experiment の 2026-09-15〜09-27（295行）で cited_article=1 が1回以上の **9本**
- 事前確認：テスト全件合格（1136 passed / 4 skipped）。`crosscom-seo-agent/output/reports/edits_20260917_0927.csv` は**存在しなかった**
- 書いたもの：`experiment_2x2/allocation_v1.csv`（46行）・`output/reports/experiment47_allocation_v1_20260928.md`（割付表の全件）
- 再現：`python experiment_2x2/allocate_47.py --seed-start 20270135 --cited-from 2026-09-15 --cited-to 2026-09-27`

| 条件 | ①対照 | ②FAQのみ | ③リードのみ | ④両方 |
|---|---|---|---|---|
| a 本数 | 11 | 11 | 12 | 12 |
| b 逆リンク追記（23本） | 6 | 6 | 5 | 6 |
| c 引用あり（9本） | 2 | 2 | 3 | 2 |
| d-1 2026-09 公開 | 2 | 1 | 2 | 2 |
| d-2 2026-07 公開 | 2 | 2 | 1 | 1 |
| e 9/15〜16 の変更（9本） | 2 | 2 | 2 | 3 |
| f 訂正対象（vibes・features） | 0 | 0 | 1 | 1 |
| g タイトル変更（3本） | 1 | 1 | 0 | 1 |

- どの組が11本になるかもくじで決まる（`allocate_47.allocate` が 12/12/11/11 を並べ替える）。今回は ①② が11本
- **agentforce-vibes（E11）は ④両方、agentforce-features（E12）は ③リードのみ**
  （9/22 の項「9/28 追記予定：3本の所属組」にも転記した）
- 9/29〜30 に本文1文の訂正が入るのは features（③）。判定は「込み」と「features 抜き」を並べる

### ビフォー期間の揺れの幅

`output/reports/experiment47_before_stability_20260928.md`（`experiment_2x2/before_stability.py` で作成）。
2026-09-17〜09-27 を前半（09-17〜22）・後半（09-23〜27）に分けた。観測単位（1行を1）の率：

| モデル | 指標 | 前半 | 後半 |
|---|---|---|---|
| Gemini | cited_article | 13.3%（8/60） | 11.6%（8/69） |
| Gemini | cited_domain | 20.0%（12/60） | 11.6%（8/69） |
| Claude | cited_article | 1.1%（1/92） | 2.2%（1/46） |
| Claude | cited_domain | 4.3%（4/92） | 2.2%（1/46） |

- Gemini の cited_article は前後半で 2pt 以内に収まったが、cited_domain は 8pt 下がった
- 組ごとは分母が 11〜24 と小さく、1件で 4〜10pt 動く。Gemini の cited_domain は ①・③ で 15〜25pt 下がった
- 観測の偏り：Gemini は日ごとに一部の記事だけを回すため、前半は 43本しか観測できていない。
  Claude は前半2回（09-17・09-21）・後半1回（09-24）で回数がそろわない
- **読み方**：組間の差が 10pt 前後でも、処置が無くても出る範囲にある。判定は再ランダム化検定の p値で読む

### 未完了・申し送り

- **再ランダム化プールはメモリ不足で未完成。判定（11/2週）までに作り直して作成する。**
  9/28 に `rerandomize.py --build` を実行したが、PC のメモリ不足で途中で止められた（ファイルは書かれていない）。
  1行ずつ追記・途中再開（`--resume`）できる形に作り直し、PC が空いている時間に作る（10/31 までに完了）
- **edits_20260917_0927.csv は 9/27 期限に未提出のため、9/29 反映前に seo-agent 側で作成させる**

確かめ方：シード・各組の本数・条件の内訳は `allocate_47.py --write` の出力と割付表の md で確認した。
揺れの幅は llm_experiment タブ（2026-09-28 取得）から集計した。

---

## 2026-09-28（続き）／再ランダム化プールの下限を 2,000 に設定

- **下限2,000・目標5,000。モンテカルロ誤差は p=0.05 付近で2,000件なら約±0.005**（sqrt(0.05×0.95/2000)≒0.0049。5,000件なら約±0.003）
- `summarize.py`：プールが **2,000件以上ならその件数で再ランダム化検定を行い「使用した割付数：N」を出す**。
  **2,000件未満なら検定を行わず「プール不足（N件／下限2,000）」と出す**（フィッシャー検定は参考として出す）
- 目標は 5,000 のまま。作成は1行ずつ追記・`--resume` で再開できる形（c6b4aa7）。PC が空いている時間に作り、10/31 までに完了させる

確かめ方：`tests/test_rerandomize.py` で 1,999件（プール不足・p を出さない）と 2,000件（検定する・件数を出す）を確かめた。

---

## 2026-09-29／B-24：複数段落回答の6本は <br> でつないで変換・判定に「複数段落回答抜き」を追加

- **B-24 の処置で、回答が複数段落の6本（②3本・④3本）は <br> でつないで変換**（文言不変）
- **処置群から外す案は、くじ引き後の除外で組の条件が崩れるため不採用**
- **判定時に複数段落回答の記事を全組から抜く感度分析を行う**
  - `summarize.py` の感度分析に5通り目「複数段落回答抜き（N本・全組）」を追加。抜くのは組に関係なく
    `has_multi_paragraph_answer=1` の全記事（処置群の6本だけでなく、①③の同じ性質の記事も抜く）。
    再ランダム化検定も同じ除外でかける
  - 表は seo-agent 側が作る `faq_multiparagraph_20260929.csv`（46本）。`experiment_2x2/` に写しがあればそれを、
    無ければ seo-agent の `output/reports/` を読む。**表が無い間は5通り目を出さず、その旨を出す**。
    46本のうち表に載っていない記事があれば、抜き漏れがありうるとして警告する
- `output/interventions.csv` に note 列を足し、I-07 に「B-24：複数段落回答の6本は <br> でつないで変換（文言不変）」を記入

確かめ方：2026-09-29 時点で faq_multiparagraph_20260929.csv は dashboard・seo-agent のどちらにもまだ無い。
5通り目の動き（全組から抜く・再ランダム化も同じ除外・表が無いとき・載っていない記事の警告）は
`tests/test_rerandomize.py` で確かめた。

### 追記（同日 18 時台）／複数段落回答の偏り

- **複数段落回答の7本は偶然すべて②④に入った（条件に入れていなかった性質）。処置は32本適用済みのためくじ引きはやり直さない。
  判定は差の差で元々の水準の差を相殺し、さらに7本を抜いた感度分析と、複数段落なしの39本だけでの比較を行う**
- 7本（seo-agent `output/experiment/faq_multiparagraph_20260929.csv`・46本すべて掲載・組の列は allocation_v1 と一致）：
  ②FAQのみ 3本（agentforce-for-sales-sdr-sales-coach・agentforce-retention・agentforce-mcp）／
  ④両方 4本（agentforce-agent-script・buyer-enablement・hyper-personalization・sfa-teichaku）／①③ 0本。
  写しを `experiment_2x2/faq_multiparagraph_20260929.csv` に置いた（判定はこちらを優先して読む）
- 感度分析の5通り目は「複数段落回答抜き（7本・全組）」になる（テストで確認）
- `summarize.py` に **FAQ の主効果の層別比較**を追加：「複数段落あり」の層は ①③ に0本のため**比較不能**と出し、
  「複数段落なし」の層（39本：②④ 16本・①③ 23本）で ②④ 対 ①③ を比べる（フィッシャーの p と差の差）。
  再ランダム化の p は同じ記事の5通り目の行を見る
- **7本すべてが②④に入る確率は未算出**。条件 a〜g を満たす割付を1,000通り作る計算（`imbalance_check.py`・
  6プロセス）が 500件を超えたところで PC のメモリ不足で止められ、途中の結果は残らなかった。
  見つけるたびに追記し、同じ設定で再実行すれば続きから作れる形に直した。参考：条件なしのくじなら
  C(23,7)/C(46,7) ≒ 0.0046（約 0.46%）

## 2026-09-29 13:13／features（post 6541）L290 の1文の誤り訂正を適用（便IX §4・便JA）

**処置ではない**（群：③リードのみ。内容を限定した例外 EXPERIMENT_PATCH_EXCEPTIONS で、この1文の置換だけを通した）。理由：提供状況の誤り訂正（管BO／管BN）。効果測定チャットの了承（便JN・2026-09-23）
- 変更前：SlackやMicrosoft Teams、ChatGPT、Claudeなど、複数の面から利用できるよう順次拡大が計画されています。
- 変更後：Salesforceの製品ページでは、SlackやMicrosoft Teams、Claude、ChatGPT、モバイルからも利用できると案内されています（2026年9月時点）。※参考記事はhttps://www.salesforce.com/agentforce/coworker/
- 見出し（【2026年8月時点】）・FAQ・メタは変えていない。apply_gate は差分がこの置換と完全一致のときだけ通す
- 一次情報：Salesforce 製品ページ（2026-09-22 取得）「…like Salesforce, Slack, Microsoft Teams, Claude, ChatGPT, and mobile.」

## 2026-09-29 13:12／処置反映の1本目：agentforce-small-business（post 6554・④両方）

- D-39 結論要約ブロック（lead_drafts_20260927.csv の block_html のまま）＋「（2026年9月時点）」を記事の最上部へ
- 既存の FAQ 5問（H3＋段落）を Yoast FAQ ブロック1つへ。Q・A の文言・問数は不変。折りたたみなし
- 既存の本文は不変（タグを落としたテキストが「足したブロックの文言＋元の本文」と一致）。apply_gate 17検査 NG0
- 公開ページ（13:13 取得）：d39-summary 1・FAQPage の Question 5・details 0
- 本田さんの目視確認を待って止めている（残りの処置群34本は未適用）。処置群35本の下見では11本が止まる（FAQ の変換10本・古い autosave 1本）→ 判断待ち
- 2026-09-29 13:22／処置反映：agentforce-roi（post 6647・③リードのみ）… D-39 あり／FAQ —（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:22／処置反映：agentforce-vibes（post 6543・④両方）… D-39 あり／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:22／処置反映：agentforce-features（post 6541・③リードのみ）… D-39 あり／FAQ —（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:22／処置反映：agentforce-in-slack（post 6545・③リードのみ）… D-39 あり／FAQ —（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:22／処置反映：agentforce-certification（post 6571・②FAQのみ）… D-39 —／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:23／処置反映：agentforce-chatgpt-copilot-comparison（post 6608・②FAQのみ）… D-39 —／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:23／処置反映：agentforce-usage（post 6606・②FAQのみ）… D-39 —／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:23／処置反映：agentforce-reasoning-control（post 6648・③リードのみ）… D-39 あり／FAQ —（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:23／処置反映：salesforce-ai（post 6825・④両方）… D-39 あり／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:23／処置反映：salesforce-data-360（post 6829・④両方）… D-39 あり／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:24／処置反映：revops-guide（post 6402・③リードのみ）… D-39 あり／FAQ —（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:24／処置反映：tableau-ai（post 6827・③リードのみ）… D-39 あり／FAQ —（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:24／処置反映：agentforce-sales-roleplay（post 7174・②FAQのみ）… D-39 —／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:24／処置反映：agentic-crm-pipeline-stagnation-detection（post 6406・④両方）… D-39 あり／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:24／処置反映：agentforce-deal-notes（post 7215・③リードのみ）… D-39 あり／FAQ —（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:25／処置反映：agentforce-voice（post 6999・③リードのみ）… D-39 あり／FAQ —（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:25／処置反映：agentforce-subagents（post 7124・③リードのみ）… D-39 あり／FAQ —（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:25／処置反映：agentforce-lost-deal-analysis（post 7153・②FAQのみ）… D-39 —／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:26／処置反映：agentforce-sales-dependency（post 7133・②FAQのみ）… D-39 —／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:26／処置反映：agentforce-data-volume（post 7186・③リードのみ）… D-39 あり／FAQ —（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:26／処置反映：agentforce-data-library（post 7127・④両方）… D-39 あり／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:27／処置反映：agentforce-permission-set（post 7130・③リードのみ）… D-39 あり／FAQ —（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:27／処置反映：agentforce-proposal-review（post 7165・④両方）… D-39 あり／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:27／処置反映：einstein-trust-layer（post 6816・③リードのみ）… D-39 あり／FAQ —（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:29／処置反映：agentforce-use-cases（post 6603・②FAQのみ）… D-39 —／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 13:29／処置反映：agentforce-testing-center（post 6643・②FAQのみ）… D-39 —／FAQ 6問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 14:00／処置反映：agentforce-for-sales-sdr-sales-coach（post 6234・②FAQのみ）… D-39 —／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 14:00／処置反映：agentforce-agent-script（post 6642・④両方）… D-39 あり／FAQ 6問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 14:00／処置反映：buyer-enablement（post 6724・④両方）… D-39 あり／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 14:00／処置反映：hyper-personalization（post 6235・④両方）… D-39 あり／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 14:00／処置反映：agentforce-mcp（post 6645・②FAQのみ）… D-39 —／FAQ 6問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 17:47／処置反映：agentforce-rag（post 6604・④両方）… D-39 あり／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 18:13／処置反映：sfa-teichaku（post 7067・④両方）… D-39 あり／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-29 18:13／処置反映：agentforce-retention（post 6260・②FAQのみ）… D-39 —／FAQ 5問（apply_gate NG0・再読一致・既存本文不変）
- 2026-09-30／drift_check：処置後の基準（46本）を experiment_2x2/drift/post_treatment/ に取得。10/5 の回は前回（9/21）ではなくこの基準と比べ、9/29〜30 の処置による変化は想定内として出さない。10/5 以降の変化は想定外として報告。読了時間の表示はハッシュから除外、本文テキストが同じで HTML だけ違う記事は別枠で出す

---

## 2026-09-29〜09-30／処置反映の完了（35本全件合格）

seo-agent の ef99696（便NL・2026-09-29 18:25）の報告から転記。

- **処置本数：②11・③12・④12 の計35本、全件合格。①11本は変化なし**（D-39 なし・FAQPage なし・内部リンク本数不変）
  - 1本目 13:12（agentforce-small-business）〜35本目 18:13（agentforce-retention）
- **features の差し替え（13:14）**
  - 前：SlackやMicrosoft Teams、ChatGPT、Claudeなど、複数の面から利用できるよう順次拡大が計画されています。
  - 後：Salesforceの製品ページでは、SlackやMicrosoft Teams、Claude、ChatGPT、モバイルからも利用できると案内されています（2026年9月時点）。
- **B-24 の例外**
  - 複数段落回答の7本は段落の間を `<br><br>` でつなぐ（文言・問数不変・折りたたみなし）。7本目の sfa-teichaku は便NL で追加
  - agentforce-retention の質問③は `<ul><li>` を保持。Yoast の回答は `<p>` の中に出るため HTML としては不正だが、
    **JSON-LD（質問③の回答にリスト3項目の文言すべて）・表示（FAQ の節の中に順に表示）とも処置は成立。凍結明けに修正**
  - 例外はすべて 2026-09-30 まで（10/1 以降は apply_gate が許さない）
- **確認スクリプトの読み違い3件を修正したうえで合格を確認**

確かめ方：seo-agent の `output/reports/bunNL_report.md`（§3〜§4）・`output/experiment/treatment_applied_20260929.csv`（35行）。

---

## 2026-09-30／アフター期間の運用：反映ラグ・アフターの開始・途中で組ごとの数字を見ない

- **反映ラグ：2026-10-01〜10-05 の観測は判定から除外**（観測の記録は続ける）
- **アフター観測：2026-10-06 以降**
- **2026-11-02 の短期判定まで、組ごとの比較（①〜④別の率・差・p値）を出さない・見ない。**
  理由：途中で覗くと、偶然の上下を見て判断してしまうため
  - 週次レポート（experiment47_weekN）は、処置反映以後の週で判定日より前に作る回は
    **46本全体の cited_article 率・cited_domain 率と欠測数だけ**を出す。記事ごとの表・引用された記事の一覧・
    社名言及の記事一覧も伏せる（記事IDと割付表から組が引けるため）。`src/experiment_weekly.py` の
    `GROUP_BLIND_UNTIL`（2026-11-02）で切り替え、テストで固定
  - **組ごとの表は判定日（2026-11-02）以降に解禁**。README（experiment_2x2）にも明記
- `output/interventions.csv` の I-07 の note に「35本全件合格・ef99696」を追記


---

## 2026-09-30／複数段落回答の7本がすべて②④に入る確率

- **条件 a〜g を満たす割付 1,000通りのうち、7本すべてが②④に入るのは 10通り（1.0%）**
  （モンテカルロ誤差 ±0.3pt 程度。9/29 の項で未算出としていた分）
- 参考：条件を付けないくじなら C(23,7)/C(46,7) ≒ 0.46%。条件 a〜g の下では約2倍起こりやすい
- ②④ に入る本数の分布（1,000通り）：0本 4／1本 47／2本 159／3本 324／4本 258／5本 163／6本 35／7本 10
- 読み方：まれ（約100回に1回）だが、条件に入れていなかった性質の偏りとしてはありうる範囲。
  9/29 の方針どおり、くじ引きはやり直さず、差の差・7本抜きの感度分析・複数段落なし39本での比較で読む
- 使った割付：再ランダム化プールが未作成のため、`imbalance_check.py` で条件 a〜g を満たす割付を
  1,000通り作った（シード 20390101 から・4プロセス・約1時間33分）。割付は
  `experiment_2x2/results/imbalance_sample_20260929.csv` に残した

---

## 2026-09-30／B-33 外部リンク別タブ化（I-14）

- **B-33 外部リンク別タブ化を 9/30 に実施（I-14）。本文不変・全記事一様のため判定では全組共通の変化として扱う。処置反映（I-07）と同時期のため、判定レポートに併記する**
- 内容：外部ドメインのリンクだけに target="_blank" rel="noopener noreferrer" を付与するフィルタ（内部リンク非作用・本文 raw の sha256 不変）。実施は管制室。
  当初の段取りは 9/29 だったが実施は 9/30
- 検証（管制室）：外部リンクへの付与を claudeforce 41本・mcp 19本で確認、内部リンク（絶対パス551本・# 1,207本）への付与0件、二重付与0件
- `output/interventions.csv` に I-14（scope=サイト全体・touches_pool46=yes）。`summarize.py` の判定レポートの冒頭に、
  判定期間と重なる scope=サイト全体 の介入を自動で並べるようにした（I-04・I-14 が出る）

---

## 2026-09-30／フォームの記録（I-15〜I-17）と、フォームの前提の再訂正

- **interventions.csv に3件を記録**（いずれも touches_pool46=no・note「L4（問い合わせ）の計測に関わる変更。実験の判定には使わない」）
  - I-15（2026-09-26・記事制作）：B-32 自作フォームの認知経路の選択肢「AI検索」の表示ラベルを「AI検索(ChatGPT・Gemini・Claude等)」に変更
    （表示のみ・保存される値 AI検索 は不変）。固定ページ4件：68 /contact/・1891 /download-paper/company-service/・
    5702 /download-paper/agentforce-support/・5801 /agentforce-business-partner/（seo-agent 便NC の記録から特定）
  - I-16（2026-09-30・記事制作）：B-32 同上。2231 /service/salesforce-implementation/・6443 /service/agentic-crm-design/・5706 /service/agentforce-support/
  - I-17（2026-09-30・制作管制）：導線是正。1337 /service/btob-marketing-strategy/ の旧事業フォームを撤去し、現行サービスへの誘導を設置
- 記録の前の照合：上の8ページ（68・1891・5702・5801・2231・6443・5706・1337）は、編集禁止49本（targets.csv）・
  新規リンク禁止47本（link_ban.csv）の**どちらにも含まれない**（URL のパスで照合。リストは URL で持っているため、
  post ID は seo-agent の報告〈便NC・便ND・便NW ほか〉の表から URL に対応づけた）
- **フォームの前提を再訂正**：measurement_design_2026-09-14.md・09-17 確定版の訂正注記のうち、「フォームは自作の多段フォームで
  送信先は Supabase の関数…」の文を「フォームは2つの仕組みに分かれている（自作フォーム7ページ＝Supabase form_submissions／
  Web-to-Lead 4ページ＝本番 Lead。1337 は 9/30 に撤去し以後3ページ）」に差し替え。原因2は仕組みごとに本番で確かめるまで未確定。
  冒頭の訂正ありの行に「（2026-09-30、フォームの前提を再訂正）」を追加（取り消し線の原文はそのまま）
- **L4 の定義**：config/kgi.yaml の official と README の正式指標の行に、保存先が2か所（Supabase form_submissions.found_us='AI検索'・
  本番 Lead の 00NQ800000Ulaeg='AIに聞いて知った(ChatGPT・Gemini等)'）で集計は両方の合計、と注記。
  Salesforce 本番側は MCP の接続先が Sandbox のため、現状は本田さんの画面での確認が必要。コードから読む処理は追加しない（L4 は判定に使わない）

---

## 2026-10-01／mentioned の判定ルールを修正（mentioned_v2）

- **2026-10-01 mentioned の判定ルールを修正し、9/15 以降の全行を answer_text から遡って再計算（mentioned_v2）。参考指標のため判定には影響なし**
- 新ルール：「クロスコム」「Cross-Com」「CrossCom」「Crosscom」「cross-com」「クロス・コム」のどれかを含めば 1
  （大文字小文字・全角半角を区別しない）。旧ルールは「クロスコム」のみ
- `llm_experiment` に列 `mentioned_v2` を追加し、9/15〜9/30 の 400行を書いた（有効 385行・欠測 15行は空欄）。
  旧 `mentioned` 列は残す（以後の行も旧ルールのまま）
- **数え直しの結果、mentioned と mentioned_v2 が違った行は 0行。** 385行すべて旧=0・新=0。
  9/15 以降の回答には、どの表記でも社名が1回も出ていない（「クロスセル」「コムデザイン」「Cross-encoder」など
  社名でない語だけ。シートの answer_text は raw_file の本文と全行一致・セルで切れた行なし）
- 週次レポートの参考欄は以後 `mentioned_v2` を使う

確かめ方：`src/backfill_mentioned_v2.py`（下見→`--write`）・`output/reports/mentioned_v2_backfill_20261001.md`。
作業は 2026-09-30 夜に実施し、ルールの適用日は 2026-10-01 として記録した。

---

## 2026-10-01／第3観測層 prompt_marketing を新設（54本・月1回）・I-07 の note を修正

- **第3観測層 prompt_marketing**（戦略管制塔の確定仕様・効果測定チャットの承認条件つき）を実装。
  54本（`config/prompts_marketing.csv`）を Gemini と Claude で月1回・毎月第1週に観測し、`llm_marketing` タブに記録。
  **実験（llm_experiment・46本）には触れない**（prompts_experiment.csv は1行も変えていない）
- **初回実行日：2026-10-01**（Claude・`marketing.yml` 10:00 JST）。Gemini は 10/1 の残りが2回のため動かず、
  **10/2（金）から**（実験の観測のあと、その日の残りの範囲で）
- Gemini の枠：実験・日次・月次の実消費を先に数え、20 からの残りが3回以上の日だけ、1本1回で残りの本数まで。
  1日の合計が20を超えないことをテストで保証。**10月は1〜14日で最大28本（残り26本は quota_skipped）**。
  層を1本ずつ順に回すので、28本の内訳は MOFU_L0 6/10・MOFU_L1 6/18・MOFU_L2 6/6・BOFU_single 5/12・BOFU_compare 5/8
- 残りが3回以上ある日（月・水・金・日の実験16本の日）の4回は、実験の 503 の取り直しと同じ余りを使う。
  実験が取り直した日は marketing の本数が減る（28本は上限）
- その月の実験で PerDay の欠測が出たら、Gemini の残りを止めてこの日誌に自動で記録する
- プロンプトの文言は初回の実行後に凍結（`tests/test_marketing.py` のハッシュ）
- `output/interventions.csv` に I-13（第3観測層の新設・scope=measurement・touches_pool46=no）を追加
- I-07 の note を「複数段落回答の7本（sfa-teichaku を含む）」に修正（6本→7本）
- `summarize.py` には mentioned_v2 の欄を置かない（判定に使わない数字を判定の出力に並べない。README に明記）

---

## 2026-10-01（続き）／第3観測層：Gemini の実行順を層ブロック順に・run_date・extractor_model・月をまたいだ比較

- **Gemini の月上限は実測で約28本。実行順は層ブロック順（L0→BOFU_single→BOFU_compare→L1→L2）で毎月固定。
  Gemini では通常 L0・BOFU_single が完結し BOFU_compare が一部、L1・L2 は観測されない月が多い。L1・L2 は Claude で毎月54本観測する。
  月をまたいだ比較は、両月で観測できたプロンプトのみで行う**
- 層をまたいだ順番回し（b9e9264）はやめた。各層の中は id 順。枠が尽きた時点で止め、残りは error=quota_skipped（翌月に持ち越さない）。
  Claude は従来どおり毎月54本すべて
- 列 `run_date`（実際に API を呼んだ日時・JST）を追加。投げていない行（quota_skipped）は空
- is_first / mention_rank の会社名一覧を挙げるモデルを `claude-haiku-4-5-20251001` に固定し、列 `extractor_model` に毎行記録。
  変える場合は README と日誌に日付と理由を書いてから変える
- ダッシュボード：ヒートマップのセルに「観測本数／層の全本数」を併記し、全本数に満たない層は「一部観測」。
  前月との差は両月で観測できたプロンプトだけで出す
- `llm_marketing` タブは初回実行の前（まだ行が無い）に列を確定したため、既存行の並べ替えは発生していない

---

## 2026-10-01（続き）／判定日程の確定と凍結明けの運用

- **長期判定 12/28 週で確定（戦略管制塔の台帳の『12月中旬』は修正依頼済み）。凍結明けは リンク張り直し → 次実験のビフォー。
  1月第1週に prompt_marketing の Gemini 54本観測（リンク張り直し中と注記）**
- 判定日程（README experiment_2x2「判定日程」に表で明記）：
  処置反映 9/29〜30／反映ラグ 10/1〜10/5（判定から除外）／アフター観測開始 10/6／
  短期判定 11/2 の週（10/6〜11/1 の観測）／長期判定 12/28 の週（10/6〜12/28 の観測。12/28 の観測分まで含む）／
  凍結 2026-09-15〜2026-12-31／解放 2027-01-01 00:00 JST
- 既存の記載との照合：反映ラグ・アフター開始・短期判定・凍結期間は README（9/30 記載）・`config/experiment_freeze.yaml` と一致。
  長期判定と解放の時刻は未記載だったため追記した
- 「実験優先の制限を外す」設定について：marketing の Gemini は元々「その日の実消費を引いた残り」を使うため、
  実験の観測が無い日は制限が自然に外れる（期間を指定する別の設定は不要）。足りなかったのは**実験の観測の終わりの日**で、
  今は終わりが無く1月も毎日続く（1月第1週の marketing は12本止まり）。本田さんの判断で
  `settings.EXPERIMENT_OBSERVATION_END`（既定は空＝終わりなし）を追加。日付を入れると翌日から実験の観測が止まり、
  1月は 1/1〜1/4 で54本を回せる（テストで確認）。実験の観測がある日は設定があっても実験優先のまま。**日付は未設定**

---

## 2026-10-01（続き）／実験の観測終了日の確定

- **実験の観測（prompts_experiment.csv の46本・Gemini＋Claude・週2回）は 2026-12-31 まで続ける**
- **長期判定に使うのは 2026-10-06〜2026-12-28 の観測。12/29〜12/31 の観測は記録のみで判定には使わない**
  （summarize は `--after 2026-10-06:2026-12-28`）
- **2027-01-01 以降、実験の観測は自動で止める（凍結の解放と同時）。E37（watch）も同日に止める**
- 設定：`settings.EXPERIMENT_OBSERVATION_END` を空（終わりなし）から "2026-12-31" に変更。experiment.yml は毎日走るが、
  計画（settings.experiment_plan）が空の日は観測せずに終わる。`config/experiment_freeze.yaml` の experiment_end（2026-12-31）と一致することをテストで確認
- 週次の「実験の Gemini 観測が目標を下回った」警告は、観測の終わりをまたぐ週から出さない（「12/31 で終了」と表示）
- 1/1 から実験の Gemini の枠が空くため、prompt_marketing の Gemini 54本は 1/1〜1/4 で終わる見込み（リンク張り直し中）

---

## 2026-10-01（続き）／記録の上書き・消失の点検

- **きっかけ：seo-agent 側で判定スクリプトによる note 列の上書きが見つかったため（手書きの記録が空欄で消えていた）、dashboard 側の記録も点検**
- 点検の範囲：ファイルまたは Google Sheets のタブに書き込むスクリプトをすべて洗い出し、書き方（追記／上書き／行の置き換え／列の置き換え）と、
  後から人・別のスクリプトが書き足す列・行の有無を突き合わせた
- **見つかった型（人が書き足したものが再実行で消える）と処置**
  - `action_log` タブ：`action_log.py --seed` を流し直すと、既存の action_id の行が丸ごと初期値で上書きされ、人が進めた状態・実施日・判断期限・備考が戻る。
    → `write_action_log` は新しい action_id の追記だけにし、既存の行には触らない（週次の提案は元々新しい番号なので影響なし）
  - `monthly_observations` タブの notes 列：観測からは埋まらない列を、同じ月の再実行で空欄に上書きしていた。
    → 書く側が空なら既存の値を残す
  - 実験の週次集計 `experiment47_weekN_*.md`：week1 に人が書き足した「**確定: 2026-09-22**」の行が、同じ日付で weekly を再実行すると消える。
    → 既にある週のファイルは書き直さない。`--force` で作り直すときも「**確定**」の行は引き継ぐ
  - いずれも「書き足してから再実行して消えないこと」をテストで確認（`tests/test_carry_forward.py`）。実際に消えた記録は無かった
- **問題なしと確かめたもの**
  - 日誌（本ファイル）：書くスクリプトは `run_marketing.py` の停止記録だけで、追記のみ・同じ記録は1回だけ
  - `output/interventions.csv`：書くスクリプトは無い（読むだけ）。人の手書きのみ
  - `llm_experiment` タブ（mentioned_v2 列を含む）：書く側が毎回 mentioned_v2 を計算して入れるため空で上書きしない。
    行数は raw（data/raw/experiment）と日付ごとにすべて一致（9/15〜10/01・452行・重複なし）、欠測でない行の mentioned_v2 の空欄 0件。
    raw は一度も削除・書き換えされていない
  - `llm_marketing` タブ：後から書き足す列は無い
  - allocation_v1.csv・experiment47_allocation_v1_20260928.md・strata_backlink_*.csv・title_changes_*.csv・rerandomization_pool.csv（未作成）と checkpoint：
    人の書き足しは無い（スクリプトの出力のみ）
- **過去の消失の確認（git の全履歴）**
  - 日誌：38コミット中、行が減ったのは5コミット・11行。すべて同じ項目の書き換え（待ち項目の確定・「（9/28 記入）」欄の記入・提案を決定に置き換え）で、
    内容が消えたものは無い
  - `interventions.csv`：12コミット中、行が減ったのは7コミット・22行。行（intervention_id）は一度も消えていない。
    取り消し線を使わずに値を書き換えたものが4件（I-07 の訂正件数 3件→2件→1件、note 6本→7本、I-04・I-05 の要確認を記入）。いずれもコミットで明示した訂正
- **再発防止**
  - 日誌と `interventions.csv` は**追記のみ**。訂正は行を消さず、追記か取り消し線（`~~旧~~ 新`）で行う。
    `tests/test_append_only_records.py` が作業中の変更と全履歴で、既存の行・セルの値が減っていないことを確かめる（上の過去の書き換え9件は確認済みとして除外）
  - README に「手で書き足す列・行を持つ表は、書き込むスクリプト側で引き継ぐ」をルールとして明記
- 点検で見えた別件（人の書き足しではなく、スクリプト自身の記録が再実行で置き換わるもの。今回は直していない）：
  同じ日の観測を再実行すると、成功していた raw と行が欠測で上書きされうる／`allocate_47.py --write` と `drift_check.py --post-baseline` は既にファイルがあっても止まらない／
  `make_strata.py` を再実行すると新しい日付の層ファイルができ、最新のものが自動で使われる

---

## 2026-10-01（続き）／出力の上書き防止を4点追加（観測の再実行・割付・ドリフト基準・層ファイルの採用固定）

- **出力の上書き防止を4点追加（観測の再実行・割付・ドリフト基準・層ファイルの採用固定）**。いずれも「既にあるものを置き換えるときは止まる。
  --force（と --reason）を付けた場合だけ置き換え、理由をこの日誌に自動で1行記録する」（`src/force_log.py`）
  1. 観測の再実行：同じ日・同じプロンプト・同じモデルで成功した raw と行が既にあれば、投げずにそのまま使い、シートの行も書き直さない。
     取り直すのは欠測（error あり）だけ。枠の都合で投げなかった記録（quota_skipped）なども、成功した raw を上書きしない。
     置き換えは `run_daily.py` / `run_experiment.py` の `--force --reason`（prompt_marketing は元々、未観測のものだけを投げる）
  2. 割付（`allocate_47.py`）：`allocation_v1.csv` か `experiment47_allocation_v1_20260928.md` があれば `--write` でも止まる。
     **実験期間中（〜2026-12-31）は --force でも止まる**（割付は実験の途中で変えない）。期間後は `--force --reason` で、旧と新のシードを日誌に記録
  3. ドリフト検知の処置後の基準（9/30 取得のハッシュと HTML 本体・`drift/post_treatment/`）：`--post-baseline` でも取り直さない。
     置き換えは `--force --reason`（取得の途中でもファイルを書くので、取る前に止める）
  4. 層ファイル：採用中のファイルを `pool.py` で名前を固定（`strata_backlink_20260925.csv`・`title_changes_20260925.csv`・`late_changes_20260925.csv`）。
     最新の日付のファイルを自動で選ぶのをやめた。新しく作っても `pool.py` の指定を書き換えない限り採用されない。指定したファイルが無ければ止まる
- 確かめ方：`tests/test_overwrite_guards.py`（成功した行を欠測で置き換えないこと・実験期間中の割付の --force が止まること・基準を取り直さないこと・
  --force の日誌への記録）、`tests/test_experiment_2x2.py`（採用中のファイル名の固定と、新しいファイルを自動で採用しないこと）
- あわせて、9/28 の weekly の push 失敗で保存されていなかった **2週目の集計（2026-09-21〜09-27）を作り直した**（`experiment47_week2_20260928.md`）。
  組ごとの比較につながる数字は 11/2 まで出さないため、記事ごとの表は伏せ、46本全体の率と欠測数だけ（`experiment_weekly.py --blind`）。
  Gemini 記事引用率 15.1%（14/93）・ドメイン引用率 15.1%（14/93）、Claude 記事引用率 2.2%（2/92）・ドメイン引用率 4.3%（4/92）、欠測 0件

---

## 2026-10-01（続き）／GSC の # 付きURLの寄せ方の確定

- **GSC の # 付きURLは本体に寄せる（表示回数・順位は本体の行のみ、クリックは合計）。GSC は判定に使わず補助分析のみ**
  （補助分析：Google 順位の上位・下位で処置の効き方が違うか）
- 本体の行が無くアンカーの行だけの記事は、表示回数・順位を「データなし」とし備考に書く（46本では該当なし）
- 9/14 版（seo-agent の `output/articles/experiment47_gsc_pages_20260914.csv`・表示回数を合算、順位を加重平均）を、上の方式で作り直した：
  `output/articles/experiment46_gsc_pages_20260914_v2.csv`（46本・E37 を除く。元のファイルは残す）
  - 元データは seo-agent の `kw_master_sheet_export_20260914.csv`（GSC「ページ」の書き出し・272行・うち # 付き 143行）。
    旧の方式で集計し直すと 9/14 版の47行と全件一致したため、これを元データと確定し、`experiment_2x2/gsc_pages_export_20260914.csv` に写した
  - 旧と新で値が変わったのは3本（アンカーの行のクリックはいずれも0件のため、クリック数はどれも変わらない）：
    E04 agentforce-observability 順位 5.86→6.03・表示回数 106→97／E19 agentforce-usage 7.63→7.61・260→258／E32 tableau-ai 8.52→8.48・353→334
- `summarize.py` の参照先を v2 に固定（`GSC_PAGES_CSV`）。ホワイトペーパーの PDF・資料DLページは46本のどれでもないため実験の集計に含めない（README に記録）

---

## 2026-10-01（続き）／GSC 補助分析：上位・下位の分け方の事前固定

- **GSC 補助分析の分け方を 2026-10-01 に事前固定（アフターのデータを見る前）。表示回数20未満は下位、20以上は順位の中央値で上位・下位。探索的分析として推定値と幅のみを出す**
- 分け方：統計46本（E37 を除く）・`experiment46_gsc_pages_20260914_v2.csv` を使う。表示回数20以上の記事で平均掲載順位の中央値を出し、
  中央値以下（数字が小さい）を上位、より大きいものを下位。中央値と同じ値は上位。表示回数20未満（とデータなし）は下位
- 結果：**上位17本・下位29本**（下位のうち表示回数20未満 12本）。表示回数20以上は34本で、**順位の中央値は 7.53**（17本目 7.45 と18本目 7.61 の平均。中央値と同じ値の記事は無し）
  - `experiment_2x2/gsc_rank_split_v1.csv` に保存。`--force` なしでは作り直さない
  - 上位は1組あたり平均4本強・下位は7本強で、「1マス5〜6本」は平均の目安（上位側はそれより少ない）
- 補助分析（`summarize.gsc_rank_subgroups`）：上位・下位それぞれの中で、リード（③＋④ 対 ①＋②）と FAQ（②＋④ 対 ①＋③）の主効果の差の差と95%の幅
  （記事のブートストラップ・種を固定）だけを出し、上位と下位で向きが逆かを1行で示す。p値・判定・再ランダム化検定は使わない
- 組ごとの比較を 11/2 まで出さないルールをこの補助分析にも適用（判定日まで実行しない）

---

## 2026-10-01（続き）／訂正：GSC 補助分析の冒頭文を実際の本数に合わせた

- 上の「GSC 補助分析：上位・下位の分け方の事前固定」で、出力の冒頭文を「1マス5〜6本のため判定には使わない」としていたのを、
  実際の本数（上位17本・下位29本）に合わせて次の文に差し替えた（`summarize.GSC_SUBGROUP_HEADER`・README も同じ文）：
  「探索的分析。1マスは上位で4本前後、下位で7本前後のため判定には使わない。State 項目8の参考。
  1マスの本数が少ないため、95%の幅（ブートストラップ）は不安定で、実際より狭く出ることがある」
- 分け方（上位17本・下位29本・中央値 7.53）とブートストラップでの幅の出し方は変えていない

---

## 2026-10-02／凍結範囲を46本に縮小（本田さん決定）・ピラー編集の判定への反映

- **2026-10-02 凍結範囲を46本に縮小（本田さん決定・事業上の改善を優先）。pricing・ピラー2本は編集可。46本の比較・リンク増減の禁止は 12/31 まで維持**
- `config/experiment_freeze.yaml` に縮小日（scope_reduced_on: 2026-10-02）と理由を記入。一覧は引き続き seo-agent の
  targets.csv・link_ban.csv を読む（49本→46本・47本→46本への書き換えは seo-agent 側が行う。2026-10-02 時点で作業中・未コミット）
- `output/interventions.csv` に I-18（凍結範囲の縮小・サイト全体・本田さん決定・touches_pool46=no）。
  **ピラー2本への孤児リンクの追加の行は、seo-agent の pillar_links_added_*.csv ができてから転記する**（2026-10-02 時点で未作成）
- 判定への反映（`experiment_2x2/pillar.py`・summarize の冒頭）：ピラー編集の完了が 10/5 までならアフター全体に同じ条件でかかるため注記のみ、
  10/6 以降ならアフターを編集前・編集後に分けた結果も並べる。seo-agent の pillar_release_balance_*.csv（組ごとの本数）を転記し、
  組間の差が2本以上なら「偏りあり」。どちらの表もまだ無いため、今は「未作成」と出る
- 参考：seo-agent 便PP（2026-10-02・測定のみ）では、ピラーA の既存リンクは ①②に厚く ③④に薄い（記事数 6・7・4・4、有意差なし）。
  pillar_release_balance が届いたら、判定レポートの冒頭で「偏りあり」と出る見込み（差3本）
- 週次ドリフト検知（drift_check.py）の対象は config/prompts_experiment.csv の46本のみ。ピラー・pricing の変化は報告されない（確認済み）

---

## 2026-10-02（続き）／ピラー編集の範囲の決定（強の重なり13本は除外）と、実施記録との食い違い

- **決定（本田さん）**：ピラー2本への孤児リンクは35本のうち「強」の重なり（46本の実験用プロンプトにそのまま答える）13本を除いた
  22本だけを今張る。13本は 2027-01-01 以降。理由：孤児が強くなると AI が46本の代わりに孤児を引用する（横取り）おそれがあり、
  その13本が③に偏っていたため（強の組み合わせ ①3・②3・③7・④0）。seo-agent への書き込みは元のセッションに一本化（-14 は書き込み停止）
- **★実施記録との食い違い（2026-10-02 dashboard 側で確認）**：seo-agent の pillar_links_added_20261002.csv では、
  ピラーA（agentforce-guide）へ 13:09:58 に20本を差し込み済みで、**強の重なり10本が含まれている**
  （agentforce-action-design・agentforce-error-tolerance・agentforce-extra-cost・agentforce-topic-design・call-center-ai・
  customer-support-ai-agent・inside-sales-ai・multi-agent・sales-ai-agent・slackbot。重なる46本の組：①2・②3・③5・④0）。
  決定の「22本のみ」とは一致しない。ピラーB はまだ記録が無い
- このため **interventions.csv への「孤児リンク22本の追加」の記録は保留**（実際に張られた内容が決まってから転記する）
- 判定への反映（`experiment_2x2/pillar.py`）：判定レポートの冒頭に 偏り1（薄まり：既存リンクを受ける46本の記事数 ピラーA ①6・②7・③4・④4、
  A・Bのどちらか ①8・②7・③5・④7。偏りあり。①②が多くリードの効果が大きめに見える方向）と、偏り2（横取り：強の13本のうち
  実際に張られた本数と組）を出す。いまは「10本が張られている」と出る。張られていなければ「対象外」と出る
- 感度分析に6通り目「ピラーの既存リンク先抜き（27本・全組）」を追加（再ランダム化検定も同じ除外）
- 表の写し：experiment_2x2/pillar_existing_links_20261002.csv・pillar_strong_overlap_20261002.csv（seo-agent の
  pillar_release_balance_20261001.md の写し）・pillar_links_added_20261002.csv（seo-agent の実施記録の写し）

---

## 2026-10-02（続き）／第3観測層：IT研修業界3本の追加（54本→57本・初回は11月）

- 戦略管制塔の依頼（本田さん承認）で、`config/prompts_marketing.csv` の末尾に MOFU_L1 の3本を追加：
  PM-L1-19（IT研修業界×Agentforce導入支援）・PM-L1-20（×Agentic CRM設計支援）・PM-L1-21（×Salesforce導入支援）。MOFU_L1 は18本→21本
- **既存54本の文言は1文字も変えていない**（ハッシュが初回実行時と一致）。文言凍結のテストは「既存54本は不変・末尾への追加は可」に更新し、
  追加3本は別のハッシュで固定（11月の初回実行後に凍結）
- **初回は 2026年11月の月次実行**。10月は既に走っているため含めない（`settings.MARKETING_PROMPT_FIRST_MONTH`。10月は54本・11月から57本）
- Gemini の実行順は層ブロック順のまま、MOFU_L1 ブロックの末尾（PM-L1-18 の次）に PM-L1-19〜21。毎月固定。Claude は毎月全本数
- 実験優先・残り枠のみのルールは変えない。57本でも1日20回以下になることをテストで確認（11月1〜14日・1月第1週は 1/1〜1/4 で57本）
- ダッシュボードのヒートマップの注記に追加：2026年11月から MOFU_L1 に IT研修業界3本を追加（18本→21本）。月ごとの層の率は月によって
  含むプロンプトが異なる。前月との差は両月で観測したプロンプトのみで計算。セルの「観測 n/全本数」の全本数は月ごとに数える
- `output/interventions.csv` に I-19（第3観測層に IT研修業界3本を追加・scope=measurement・戦略管制塔〈本田さん承認〉・touches_pool46=no）

---

## 2026-10-02（続き）／ピラー編集の確定（強10本を外した）と記録

- **2026-10-02 13:09 別セッションがピラーAに確定前の計画で20本を追加（強10本を含む）。強10本は外す決定。書き込みは 9d に一本化**
- seo-agent の記録（pillar_links_added_20261002.csv・完了報告 bunPV）：
  - 13:09:58 ピラーA に20本を追加（並行セッション -14・強10本を含む）
  - 13:22:57 ピラーA から強の10本を外す（9d）
  - 13:24:32 ピラーB に強でない孤児9本を追加（9d）
  - 13:34:55 ピラーB から agentic-crm-sales-enablement を外す（9d・保留に加えたため）
- **最終状態は 18本（ピラーA 10本・ピラーB 8本）**。強の13本は1本も入っていない。46本へのリンクの増減は0（seo-agent の diff 検証）。
  当初の「強でない22本」とは違う：本田さんの判断で agentic-crm-sales-enablement を保留に加え（保留14本・対象21本）、
  そのうち見出しの新設が要る3本（sales-back-office・agentic-crm-abm-roi-measurement・agentic-crm-abm-sales-handoff-scoring）は 1/1 バッチ
- **ピラー編集の完了は 2026-10-02 13:34:55（最後の操作）＝10/5 以前**。アフター期間（10/6〜）の全体に同じ条件でかかるため、
  判定ではアフターを分けない（注記のみ）。偏り2（横取り）は、強の重なりが1本も張られていないため対象外
- `output/interventions.csv` に I-20〜I-23（4操作。touches_pool46=yes。note に最終状態と 10/5 以前に完了したこと）
- `experiment_2x2/pillar.py` を新しい記録の形（action＝add/remove）に合わせた：最終状態の本数と最後の操作の日時を判定レポートに出す

---

## 2026-10-02（続き）／I-23（sales-enablement の保留）の決定者の確定（追記）

- 上の「ピラー編集の確定」の項の「本田さんの判断で agentic-crm-sales-enablement を保留に加え」は**正しかった**。
  seo-agent の調査（af2e9cd）と本田さんへの確認で、決定者は本田さんと確定した
- 経路：2026-10-02 13:09 に別セッション（-14）が sales-dependency と強く重なると判定 → 便PU（制作管制）で「保留14本・本田さん確認済み」→
  本田さんが効果測定チャットで本人確認済み → 9d が 13:34:55 にピラーBから削除
- **sales-enablement の保留は効果測定チャットの指示ではない**（効果測定チャットが保留にしたのは「強」の13本のみ）。
  seo-agent の重なりの判定では「弱」（E41 agentforce-sales-dependency）
- `output/interventions.csv` の I-23 の note に決定者を追記（既存の記述は消さず追記のみ）

---

## 2026-10-03／第3観測層の Claude 部分を停止（費用削減・本田さん決定）

- **prompt_marketing の Claude の観測を停止**（`marketing.yml` はリポジトリ変数 `MARKETING_CLAUDE_ENABLED='1'` のときだけ走る。
  `run_marketing.py --model claude` も同じ設定を見る）。10月の Claude は全54本を観測済み（10/1 は50本がクレジット残高不足で欠測→10/2 に取り直し）
- **is_first / mention_rank の Haiku 抽出を停止**（`MARKETING_RANK_ENABLED`）。停止中の行は両列が空、`extractor_model` は「停止中」。
  順位の月次比較は 2026-10 の Claude 分（54本）だけが基準として残る
- **Gemini は継続**（無料枠・実験優先・層ブロック順は不変）。記録は mentioned・cited_domain・cited_domains・answer_text
- 前回依頼の「途中切れ7本（BC-02/05/06/07、L1-02/10/11）の取り直し」と「max_tokens を 4096 に」は**取り消し**。
  `stop_reason` の記録のみ続ける（費用ゼロ。raw の stop_reason。10月分の7本は記録前のため理由は不明のまま）
- **実験（llm_experiment）は変更なし**。実験の Claude 観測（月・木 47本）・日次・月次の観測はそのまま
- 再開は変数を '1' にするだけ。`output/interventions.csv` に I-24（scope=measurement・touches_pool46=no）

---

## 2026-10-03（続き）／実験の Claude 観測を週2回→週1回に（2026-10-05 から・費用削減・本田さん決定）

- **2026-10-05（月）から実験の Claude は月曜のみ**（木曜を止める）。watch（E37）の Claude も月曜のみ。**Gemini の観測は不変**。
  ビフォー（〜9/28）は週2回のまま記録として残す。アフター観測（10/6〜）の開始前に切り替えた（10/1 の木曜が最後の木曜の観測）
- **判定の Claude 分は観測1回あたりの率で比べる**（`summarize.py`）：記事ごとの「cited_article=1 の回数 ÷ 観測できた回数」で
  ビフォーとアフターを比較し、差の差も率の差で出す。これまで Claude も「期間中に1回でも引用されたか」の0/1だったが、
  ビフォー週2回・アフター週1回では回数の差がそのまま差に見えるため置き換えた。率にはフィッシャー検定を使わない（「—」）。
  再ランダム化検定（判定の本線）は率の平均の差で行う。**Gemini（主指標）の判定は不変**
- 週次サマリに実験の Claude の行（目標＝46本×その週の観測日数。10/5 以降の週は46本）を追加
- `output/interventions.csv` I-25
- **戦略管制塔の台帳指示（2026-10-03）**：
  - PM-L1-19〜21 の初回ベースラインは、prompt_marketing の観測再開時（業界シリーズ公開開始時の再評価、または 2027年1月の
    Gemini 枠解放）まで延期
  - I-24（prompt_marketing の Claude 停止）を戦略管制塔が 2026-10-03 に追認。10月 Claude 分54本はフルベースラインとして保全（補修なし）。
    I-24 の note に追記（既存の記述は消さず追記のみ）

---

## 2026-10-03（続き）／Claude API の呼び出し上限（暴走防止）

- **自動チャージは使わない。1日の呼び出し上限と 400 での即停止で暴走を防ぐ。残高は 10/25・11/25 ごろに本田さんが手動で確認・チャージ（目安 $35）**
- Claude API を呼ぶすべての処理（実験・日次・月次・Haiku 抽出・週次所見・prompt_marketing）が `claude_budget.guard()` を通る。
  上限は `config/claude_budget.yaml`（月曜＝実験の日 60回・その他 30回・月次の日 +25回）。上限に達したらその日の残りは error=daily_cap
- クレジット不足（400）は再試行せず、その日の Claude 呼び出しをすべて止める（credit_exhausted）。10/1 のように50本すべてに投げることはなくなる
- 止まったら各ワークフローの最後の「Check Claude daily cap」が実行を失敗にし、Slack に通知する。Gemini の観測は影響を受けない
- 実験の設定（max_tokens 2048・Web 検索 最大5回）は変えていない（確認のみ）

---

## 2026-10-03（続き）／引用プローブの上限漏れを塞いだ

- 引用プローブ（`experiment_2x2/llmo_probe.py`）は API を HTTP で直接呼んでおり、`claude_budget` の上限を通っていなかった
- **実験期間中（〜2026-12-31・experiment_freeze.yaml の experiment_end）は、実行しても API を呼ばずに終了**（--force でも呼ばない）。
  `resume_probe.py`（中断した観測の続き）も同じ。これまでは probe.yml の期間チェックだけで、手元で直接実行すれば呼べた
- 2027-01-01 以降は Claude の呼び出しが `claude_budget.guard()` を通る（1日の上限・400 のクレジット不足で即停止）
- リポジトリ全体を検索した結果、Anthropic を直接呼ぶ処理はほかに無い（観測・Haiku 抽出・週次所見・順位の抽出は bb50486 で上限を通っている。
  `reextract_negative.py` と `tests/manual_extract_negative_check.py` は extract.py 経由で上限を通る）。素通りする処理が増えたらテストで落ちる

---

## 2026-10-03（続き）／再ランダム化プールの二重実行の確認と点検

- **二重実行は無かった**。「2プロセス」に見えたのは、Windows の `python.exe`（Microsoft Store のアプリ実行エイリアス）が
  本体の Python を子プロセスとして起動していたため：PID 27928（ランチャー・CPU 0.08秒）→ 子 PID 27248（本体・CPU 約10,159秒）、
  どちらも 12:15:49 開始・親は nohup（PID 26228）。プール作成は1つだけで、止める必要は無かった（前回の報告の「2プロセス」は誤解を招く書き方だった）
- **点検（15:14 時点・1,126行）**：シードの重複 0・割付（46文字）の重複 0・長さ違い 0。全行が allocate_47.check の条件 a〜g を満たす。
  全行がシードから同じ割付を再現できる。採用された割付（シード 20270135。allocation_v1 と一致を確認）と同じ割付は 0行。
  perm_id は1から連番、シードは昇順。checkpoint の最後に試したシード（38370100）≥ プールの最大シード（38360039）で矛盾なし、
  checkpoint の件数とファイルの行数は一致。重複・条件違反が無いため列 invalid は足していない
- **二重起動の防止**：作成中は `results/rerandomization_pool.csv.lock`（プロセスID・開始時刻・コマンド）を置き、ロックがあれば
  2つ目の --build / --resume は起動せずに終わる。ロックを置いたプロセスが動いていなければ（強制終了の残り）置き換える。
  ロックを持たせるため、15:16 に作成を止めて（強制終了・1,126行で点検済み）、新しいコードで1プロセスだけ `--resume` で再開した。
  2つ目を起動して拒否されることを確認
- 同日に別件：seo-agent が 15:08 にピラーB（agentic-crm）へ46本の外の3本へのリンクを追加した記録（pillar_links_added_20261003.csv）を出した。
  `pillar.py` が一番新しい日付のファイルだけを読んでいたため 10/02 の記録が抜けていた → 日付ごとのファイルを全部合わせて読むように直した。
  最終状態は A10・B9 の19本（cs-handback・role-design は 10/02 にリンク済みで2本目のリンク、migration-decision が新しい1本）、強は0本、
  完了は 10/03 15:08（10/5 以前なのでアフターは分けない）

---

## 2026-10-03（続き）／10/03 のピラーB編集を記録（I-26）

- seo-agent（9d）が 2026-10-03 15:08 にピラーB（agentic-crm）へ孤児リンクを3件追加（すべて46本の外の記事）。
  cs-handback・role-design は 10/02 にリンク済みの記事への2本目のため、リンクされている記事の数は1本増（agentic-crm-migration-decision）
- 強の重なり0本。**最終状態 A10・B9 の19本**。**ピラー編集の完了は 2026-10-03 15:08**（10/5 以前のため、アフター期間は分けない）。
  記録は crosscom-seo-agent の pillar_links_added_20261003.csv
- `output/interventions.csv` に I-26（scope=ピラーB・touches_pool46=yes）。I-23 の note に「最終状態は 10/03 15:08 の追加で A10・B9 の19本に更新（I-26 参照）」を追記（既存の記述は消さず追記のみ）
- 判定レポートのピラー編集の欄が「完了 2026-10-03 15:08:33・最終状態 ピラーA 10本・ピラーB 9本（計19本）」と出ることを確認（テストで固定）

---

## 2026-10-06／Gemini の時間切れと、Claude が止まっても Gemini を続ける仕組み

- **10/05（月）の実験の Claude 47本が欠けた**：Gemini の10本目（10:47）で応答が返らず、ジョブの4時間制限（14:31）で打ち切られ、
  Claude の観測まで進まなかった。10/05 は反映ラグ（10/1〜10/5）のため判定には使わない
- **10/06 からクレジット切れ**：日次は Claude の最初の1回で 400 → 即停止（10/03 の仕組みが働いた）。ただし抽出も Claude のため、
  Gemini の7本も抽出されず、llm_observations に空の行、daily_summary に言及率 0% が書かれた（実際は「分からない」）
- 対処（本田さん指示）：
  - Gemini の1回の呼び出しを180秒で打ち切り、503 と同じ扱いで取り直す
  - 実験のワークフローを「待ち（最大90分）」と「観測（制限1時間）」の2つのジョブに分けた（4時間→1時間）
  - Claude が止まった日の抽出は「抽出保留」として台帳（data/extract_pending）に残し、シートに空の行・0% を書かない。
    Claude が使える日の日次で後日まとめて抽出し、その日の言及率・言及シェアを作り直す
  - 10/06 の Gemini 7本を台帳に登録（チャージ後の最初の日次で直る）

---

## 2026-10-06（続き）／【計画の変更】Claude API の全停止（費用ゼロ方針・本田さん決定）

- **2026-10-06 Claude 観測を停止（費用ゼロ方針・本田さん決定）。アフター期間（10/6〜）の Claude データは0本のため、Claude は判定対象外とする。主指標は事前登録どおり Gemini のみで変更なし。この変更はアフター期間の実験データを見る前に行った。**
- クレジットは今後チャージしない。残高切れの失敗に任せず、`config/claude_budget.yaml` の planned_stop_from（2026-10-06）で日付を決めて止めた（上限0）。再開は null にするだけ
- 停止中の Claude の観測は**行を作らない**（欠測の error 行と区別できる。欠測にも数えない）。失敗の通知・上限の警告は出さない
- 週次所見は Claude を使わず**数値の表だけ**で出す（失敗にしない）
- 実験の判定は Claude を判定・感度分析・補助分析から外し、「判定対象外」と表示。冒頭に一般化できない旨を明記。Gemini の判定は不変（テストで確認）
- 日次・月次の抽出（Gemini の回答の社名・否定の判定）も Claude（Haiku）のため「抽出保留」になる。抽出を Gemini に移すまで日次の指標は空（0% ではない）
- 予定の計算：10/6〜10/12 の1週間と 12/28（最後の月曜）で Claude の呼び出し0回・上限0、Gemini の観測の本数と割当は停止前と同じ（テストで確認）
- interventions I-27・experiment_freeze.yaml の plan_changes に記録。ビフォー（9/15〜9/28）の Claude データは残す

---

## 2026-10-06（続き）／抽出と週次所見を Gemini に移行（本田さん承認）

- **枠の確認**：Gemini の無料枠の1日の上限はモデルごと（429 の quotaDimensions が model 単位・gemini-2.5-flash は20回）。
  gemini-2.5-flash-lite は「新規の利用者には提供終了」（404）のため **gemini-3.5-flash-lite** を抽出に使う。検証で100回続けて呼び、429 は0回（1日の上限は100回以上）。
  日次の日7回・第1水木 +6回は収まる。観測（gemini-2.5-flash）の20回は使わない
- **精度の検証**：過去の回答100本で既存の Haiku の抽出と突き合わせ、**mention 100%・negative_or_outdated 99%**（基準95%以上を満たす）。
  食い違い1本（E-1・Claude の回答。「BtoB MA導入・運用支援」の現在形を Gemini は true、Haiku は false）。記録は output/reports/extract_gemini_validation_20261006.csv
- **週次所見**は gemini-3.5-flash（10/05 の stats で試し、2,326字・記述ルールの警告なし）
- **抽出保留の台帳（10/06 の7本）を抽出してシートを埋めた**：Gemini 6本に抽出結果、E-1 は観測そのものが 429 の欠測（元から）。
  10/06 の言及率は 66.7%（6本中4本）、sov_daily に52行（Gemini のみのため通常の半分程度）。台帳は空になった
- **注意（README「Claude をやめて失うもの」）**：9/22〜10/03 の否定の検知はすべて Claude の E-1。10/06 以降に R-P7 が発火しなくなっても、
  古い情報が解消したとは読まない（観測するモデルが減った結果）。日次の言及率・言及シェアは 10/06 から Gemini だけ（母数が半分）で、前後を直接比べない
- 作業中の事故：抽出を Gemini に切り替えた直後のテスト実行で、手元の GEMINI_API_KEY により本物の抽出（gemini-3.5-flash-lite）が数十回以内走りかけた
  （約2分で停止。シートへの書き込みは無し・観測の枠は使っていない）。テストでは API の鍵を必ず外すようにした

---

## 2026-10-06（続き）／R-P7 と言及率の誤読防止

- Claude 停止中は、R-P7 の注記（「R-P7(ネガティブ/古い情報)はGeminiの観測のみで判定している。…発火しないことを解消と読まないこと」）を
  週次所見の §5（モデル任せにせず必ず入れる）・アプリの R3 のキャプション・Looker の lk_events に出す。Looker の「使い方」ページの文面は手で貼る
- 言及率の母数が 2026-10-06 に 14本→7本に変わったことを、アプリの R2 の一点鎖線と lk_events の「計測の変更」、10/12 の週次所見 §5、README に記録

---

## 2026-10-07／判定レポートの交絡候補一覧の範囲を広げた（本田さん決定）

- 「判定期間と重なる介入」の欄を「アフター期間中のサイト全体施策一覧（判定の交絡候補）」にし、scope が サイト全体／site_hygiene／cta／ピラーA／ピラーB／measurement の行を
  touches_pool46 に関係なく載せる（括弧より前で比べる）。interventions.csv の scope は書き換えない。判定の数値は変わらない（テストで確認）
- 今日の時点で短期判定・長期判定とも13行：I-04・I-14・I-18（サイト全体）、I-20〜I-23・I-26（ピラー）、I-13・I-19・I-24・I-25・I-27（measurement）。
  site_hygiene・cta の行はまだ無い。I-15〜I-17（フォームの表示ラベル）は scope が「固定ページ…」のため載らない
- seo-agent のサイト整理（26行）は実行記録待ち。届いたら scope=site_hygiene で追記し、この一覧に載ることを確かめる

---

## 2026-10-07（続き）／交絡候補一覧を全介入に広げ、見出しを実態に合わせた（本田さん決定）

- scope による絞り込みをやめ、判定期間（ビフォーの初日〜アフターの最終日）に日付が重なる interventions.csv の全行を載せる。
  見出しは「判定期間（ビフォー〜アフター）中のサイト施策一覧（判定の交絡候補）」。scope ごと（括弧より前）にまとめ、プール46本に触れる行を含む scope が先
- 今日の時点で短期・長期とも24行＋日付不確定1行（I-05）：
  I-09（統計46本のうち9本＋ピラー）／I-04・I-14・I-18（サイト全体）／I-07（プール46本）／I-20・I-21（ピラーA）／I-22・I-23・I-26（ピラーB）／
  I-01・I-02・I-03（外部）／I-08（実験外）／I-06・I-10（サイト）／I-15・I-16・I-17（固定ページ）／I-13・I-19・I-24・I-25・I-27（measurement）。
  I-11・I-12 は 9/14 までに終わったため判定期間の外
- 判定の数値（差の差・p値・感度分析）は変わらない（テストで確認）

---

## 2026-10-07（続き）／早期解放ルールの実装（短期判定のデータを見る前）と scope のまとめ方

- **早期解放ルール：2026-10-07 に実装（短期判定のデータを見る前）。条件の内容は 2026-10-01 の事前登録どおり。**
  短期判定（2026-11-02 の週）の出力にだけ、施策ごと（リード／FAQ）に (1) Gemini の差の差 +20ポイント以上 (2) 再ランダム化の片側 p<0.005
  （プール2,000件未満は判定不能）(3) 感度分析の全通りで向きが同じ、の3条件と「解放可／解放不可」を出す。Claude は対象外。
  境目（ちょうど +20 は合格・ちょうど 0.005 は不合格）・プール不足・Claude を使わないことをテストで固定。experiment_freeze.yaml にも記録
- p は判定の本線と同じ再ランダム化検定（アフター期間の組の差で数える。差の差ではない）
- **再ランダム化プールの作成が 10/03 15:39 から止まっていた**（1,230件）。10/03 15:16 の再開のあと約23分で、シェルの終了とともに止まったとみられる。
  10/07 23:06 に Windows の独立したプロセスとして再開（ロックは新しいプロセスに置き換わった）。条件 c はシートを読み直さず checkpoint の値を使うように変更
- **シートが読めない**：10/07 夜、サービスアカウント llmo-collector@crosscom-llmo.iam.gserviceaccount.com がスプレッドシートを読めなくなっている（403・PermissionError）
- interventions.csv の scope は「括弧より前・末尾の数字＋件を除く」でまとめる（固定ページ4件／1件／3件 → 固定ページ）。今後は scope に件数を入れない

---

## 2026-10-07（続き）／シートの 403（共有設定）と書き戻し

- **403 の期間**：始まりは 2026-10-07 11:22 JST（実験の Actions がシートに書けた最後）より後、23:05 JST（手元で最初に 403）より前。
  終わりは 23:27 JST の確認時点で読み書きできた（本田さんが共有を直した）。原因は共有設定（サービスアカウント llmo-collector@crosscom-llmo.iam.gserviceaccount.com の権限）
- **この期間に Actions がシートに書く予定は無かった**（日次・月次・実験は朝に書き終えていた）。data/raw とシートを 9/15 以降で突き合わせ、
  **403 で失われた観測は0件**（llm_observations・llm_marketing・monthly_observations は raw の全件がシートにある）
- 突き合わせで見つかった別の欠け：**llm_experiment の 10/05**。原因は 403 ではなく、10/05 の実験ジョブが Gemini の応答待ちで4時間制限に達したこと
  （raw は保存済み・シートに書く前に打ち切られた）。`backfill_experiment_sheet.py` で書き戻した：
  - raw からの書き戻し **9行**（Gemini E28〜E36。判定列を付け直し、リダイレクトは全件解決できた）
  - **本当に欠けた観測 54行**（raw も無い）：**Gemini E37〜E43（7本。プール46本では E38〜E43 の6本・E37 は watch）**、Claude E01〜E47（47本）。
    error=job_timeout として raw・シート・実験日誌に記録（403 ではないので sheet_unavailable にはしない）
  - 10/05 は反映ラグ（10/1〜10/5）で判定には使わない
- 既存の行は消さず、重複も無い（llm_experiment 518行→581行・同じ鍵の行は0）
- 再発防止：観測は raw に先に保存してからシートに書く順になっている（collect が1件ごとに raw を保存・シートは呼び出し側があと）。
  Sheets が 403 を返したら Slack に「シートの共有を確認」と1回だけ通知する（sheets_writer の HTTP クライアント）
- 参考：10/07 の実験の Gemini の欠測5件（E08・E09・E11 は Gemini 側の時間切れ、E17 は 503、E18 は 429）は朝の実行時の provider 側の欠測で、403 とは無関係

---

## 2026-10-08／組ごとの欠測の監視と Ahrefs のタグ（I-28）

- 週次集計に「組ごとの欠測（実験の Gemini・本数のみ）」を追加。その週とアフター期間（10/6〜）の累計を①〜④で並べ、累計で組の間の差が3本以上なら警告。
  引用率・差は出さない。10/08 時点の値：その週（10/05〜10/11）①4・②3・③1・④3、アフター累計 ①2・②1・③0・④2（差2本・警告なし）
- interventions.csv に I-28（2026-10-07 Ahrefs Web Analytics のタグ再設置・measurement・記事制作・touches_pool46=no）を追記

---

## 2026-10-08（続き）／観測ジョブの時間の予算と観測順の並べ替え（本田さん決定）

- **2026-10-08 観測ジョブに40分の時間の予算と、日付を種にした観測順の並べ替えを導入。時間切れの欠けが組に偏らないようにするため。巡回の割り当ては不変。**
- 時間の予算：ジョブの開始から40分を超えたら新しい Gemini 呼び出しをやめ、残りは error=time_budget として raw・シート・日誌に記録して正常に終わる（180秒の打ち切りはそのまま）
- 観測順：その日の実験の記事を日付（YYYYMMDD）を種にした乱数で並べ替える。割り当て（どの日にどの記事か）と本数は不変（テストで確認）
- 週次の「組ごとの欠測」に欠測の種類ごとの本数を追加
- interventions I-29

---

## 2026-10-08／prompt_marketing（2026-10）を停止（自動記録）

- その月の実験の観測で 429 PerDay の欠測が出たため、Gemini の prompt_marketing の残り 52本を error=quota_skipped として記録し、今月はこれ以上投げない（run_marketing.py）
- 実験の PerDay 欠測: 2026-10-07 E18
- Claude の prompt_marketing は Gemini の枠と無関係のため止めない

---

## 2026-10-08（続き）／MA 移設に伴う感度分析の追加（記録の準備）

- 本田さん決定で MA・メールマーケ28本を note へ移設（実施時期は戦略管制塔が確定）。凍結46本のうち buyer-enablement（E23）の被リンク4本・hyper-personalization（E27）の1本が減る
- **E23・E27 とも ④両方。被リンク減は④のみに起きるため、リード・FAQの効果とも小さめに出る方向（保守的）**（allocation_v1 で確認）
- 感度分析に「リンク減2本抜き」と、9本抜き・複数段落回答抜きとの組み合わせを追加（2本とも両方に含まれるので組み合わせは元の通りと同じ記事を抜く）。
  再ランダム化検定・早期解放の条件(3)も含む。experiment_flag は維持・主分析は46本のまま
- 実施日時が seo-agent から届いたら interventions.csv に scope=site_structure で追記する。判定レポートの注記（アフター期間中の被リンク減）と交絡候補一覧には自動で載る

---

## 2026-10-08（続き）／Gemini の1分あたり上限への対処と感度分析の重複整理

- 10/08 の日次で E-1 が 429（1分あたり・1分5回）で欠けた。Gemini の観測の呼び出しの間を13秒空け、1分あたりの 429 は待って取り直す（取り直しは1日20回の枠に数える）。
  1日あたりの 429 は従来どおり取り直さない（quotaId の PerMinute／PerDay で区別できる）。測り方（質問・モデル・回数）は不変。失敗による欠測を減らすための変更（interventions I-30）
- 感度分析：抜く記事の集合がまったく同じ行を1行にまとめた（9本抜き＝9本抜き＋リンク減2本、複数段落回答抜き＝複数段落回答抜き＋リンク減2本）。7通りになった。
  早期解放の条件(3)はまとめた後の全行で判定（中身は変わらない）
- MA 移設：実施は10月中・全量で確定（戦略管制塔）。実行は seo-agent（9d）。2記事のリンクが消えた日時が届いたら interventions.csv に追記する。区切りは遅いほうの日時
- 再ランダム化プールを commit する手順を README に記録

---

## 2026-10-08（続き）／10/08 の日次の欠測1件の原因と、日次の終了コード

- 10/08 の日次の欠測1件は **E-1 × Gemini**。**429 の1分あたりの上限**（quotaId GenerateRequestsPerMinutePerProjectPerModel-FreeTier・1分5回）。
  10:34:40〜10:35:29 に7本を約50秒で投げ、7本目で当たった。当時は 429 を取り直さない作りだったため、取り直し0回・掃き直し0回（掃き直しは 503 だけ）で欠測。
  同日中に13秒間隔と1分あたりの 429 の取り直しを入れた（I-30）
- 日次の終了コードを実験と同じ方針にした：429 だけ・503 由来1件だけは警告（exit 0）、503 由来2件以上・認証・例外・観測なしは失敗（exit 1）

---

## 2026-10-09／著者表示と Person 構造化データ・著者ボックスのオフ（制作管制から連絡）

- 2026-10-09 19:42 に全ページへ2件を実施（seo-agent（9d））。interventions.csv に追記：
  - **I-31** 著者の自動表示と Person 構造化データを全ページに適用（touches_pool46=yes。全ページ一律・4組に同条件。46本の本文は不変）
  - **I-32** テーマ標準の著者ボックスを全ページでオフ（touches_pool46=yes。本文の変更なし）
  - 「著者の自動表示」の既存の行は無かったため新規に追加。**アフター期間中のため交絡候補**。判定レポートの交絡候補一覧（サイト全体）に2行とも載ることを確認
- 同日 21時台に46本の公開ページを取り、10/05 の基準と比べた（基準は書き換えていない）：
  - 46本とも差分は13行で同じ。冒頭の「著者：本田正憲／合同会社クロスコム 代表／Salesforce認定コンサルタント」、末尾の新しい著者欄（紹介文・プロフィールを見る →）の追加と、
    旧テーマの著者ボックス（旧紹介文・note へのリンク・記事一覧へ）の削除だけ。**著者欄以外の変化は0本**
  - 紹介文の文面は変わった（旧：専門商社7年・認定資格3つ・note リンク → 新：双日グループの専門商社・2023年設立）。著者欄の中の変化として扱う
  - Person 構造化データは46本すべてにある（<script> の中なのでドリフト検知の差分には出ない）
- ドリフト検知（drift_check.py）：10/09 以降、差分の行がすべて上の著者欄の行（文字列で照合）なら「想定内の変化」として別枠に出し、想定外には数えない。
  著者欄以外の行が1行でも変われば、紹介文の書き換えを含めて従来どおり想定外として出す。次の回（10/12）で46本が想定内に入る見込み（10/09 に実ページで確認済み）

---

## 2026-10-10／観測プロンプトの重複は統合しない（意図的な反復測定ペア）

- 日次・月次・第3観測層の73本を調べ、4軸が同じ組が4組あった（`output/reports/prompt_overlap_2026-10-10.md`）。
  G1：A-1／M-10／PM-L0-01、G2：M-12／PM-L2-05、G3：M-3／PM-BS-02、G4：M-4／PM-BS-10
- **本田さん決定：統合は見送り。4組は意図的な反復測定ペアとして残す**（空く枠は1日0.1回ほど。M-12 と PM-L2-05 は一字一句同じなのに
  1日違いで結果が分かれた＝同じ質問の揺れ幅を知る材料）。README に記録し、将来の整理で統合しないよう明記
- 週次サマリに「反復測定ペアの食い違い（直近4週・言及の有無）」を1行追加。10/12 の回の見込みは 5回中1回（G2 の1回）
- **確認予定（2026年11月）**：G3・G4 の社名の表記の違い（「合同会社クロスコム」とそれ以外）。11月に M-3・M-4 と PM-BS-02・PM-BS-10 の
  Gemini の観測が両方そろった時点で答えを比べ、同名他社との混同（別の「クロスコム」を挙げる・実績を取り違える）の有無に差が出るかを確かめる。
  第3観測層の Gemini は残り枠で動き、BS 層は順番が2番目なので、11月に第3の Gemini が動けば取れる見込み。そろわなければ12月に持ち越す

---

## 2026-10-11／MA 移設で E23・E27 の被リンクが減った（日時確定・I-33）

- seo-agent（9d）から日時が届いた（元：crosscom-seo-agent/output/reports/bunTG_pool46_link_loss_handoff）。2026-10-11 に MA・メールマーケ記事5本を note へ 301 転送し、サイト側を下書き化：
  - buyer-enablement（E23・④）：email-marketing-strategy 21:23:45・marketing-automation-lead-generation 21:24:16・marketing-automation-btob 21:24:41・email-marketing-contents 21:25:10（−4）
  - hyper-personalization（E27・④）：marketing-automation-machine-learning 21:25:36（−1）
  - 転送後、凍結46本は46本とも HTTP 200（seo-agent 確認）
- interventions.csv：seo-agent 側が書いた行は**無かった**（dashboard 側だけが書く運用どおり）。**I-33** を1行で追記（scope=site_structure・touches_pool46=yes・note に各時刻と indirect の旨）
- 感度分析の区切り日時は遅いほうの **2026-10-11 21:25:36**（`summarize.link_loss_at` が I-33 の note から読む）。
  「リンク減2本抜き」は E23・E27 を期間全体で抜くため、区切り日時で数字は変わらない（注記と表示のため）。
  なお 10/11 の実験の観測（16本・10:31〜10:38 JST）は移設より前
- 判定レポートの注記「アフター期間中（2026-10-11）に E23・E27 の被リンク減あり。いずれも④。リード・FAQの効果とも小さめに出る方向（区切り日時 2026-10-11 21:25:36）」が
  短期判定（11/2 の週）・長期判定の両方に出ること、交絡候補一覧の site_structure に I-33 が載ることを本物の行で確認（テストで固定）

---

## 2026-10-16／実験の Gemini で 503 の欠測8本（アフター期間）と、失敗通知の原因表示

- **10/16（金）の experiment.yml #32 が異常終了。原因は Gemini の 503（"This model is currently experiencing high demand"）の連続**。
  認証エラー・コードの例外ではない（実行ログ・実験日誌で確認）
- **アフター期間（10/6〜）の観測日**。判定に使う期間の欠測
- 計画16本（日次・月次なしの日・取り直しの枠は 20−16＝4本）。観測 8/16、**欠測8本：E02・E37・E38・E40・E44・E45・E46・E47**（すべて 503・attempts 1）
  - E37 は watch（割付なし）。凍結46本の欠測は7本
  - 組ごとの欠測（本数のみ）：10/16 は ①0・②2・③3・④2。アフター累計（10/06〜10/16）①3・②3・③4・④4（組の間の差1本・警告の3本未満）
- **取り直しの回数**：再試行4回（E39 が3回目で回復・E34 が1回目で回復）で枠4本を使い切り、その後の8本は再試行0回。
  掃き直しは1回目（60秒後）が「枠の余りが尽きた」で1件も投げずに打ち切り、2回目（180秒後）は走らず。**掃き直しで投げた回数は0回**。
  Gemini の呼び出しは計20回（16＋4）で、1日の上限ちょうど
- 欠測の8本はその日のうちに取り直していない（枠は使い切り。後日の取り直しは翌日の枠を食うため行わない。これまでの欠測と同じ扱い）
- **月曜の過去2回**：
  - 10/12（月）：同種の 503。E32 が初回＋再試行3回とも 503 で枠4本を使い切り、掃き直し1回目（60秒後）で回復。欠測0本。**枠がぎりぎりで足りた日**
  - 10/05（月）：503 ではない。Gemini の応答が返らずジョブの4時間制限で打ち切り（job_timeout。10/06 の節）。反映ラグの期間で判定外
- 503 の週次監視：直近2週 4件／8件（警告は週5件超が2週続いたとき。今週が5件超の1週目）
- **対処（コード）**：
  - 失敗通知を「503の欠測・認証エラー・例外」の3つ並べから、実際の原因の1行に変更。
    例：「• 原因: 503の欠測 8件(E02, E37, E38, E40, E44, E45, E46, E47)。取り直しの枠4本を使い切り(再試行4回・掃き直し0回)」。
    認証エラーは文面つき、例外はフェーズ名つき。prompt_marketing・commit・Claude の上限のステップが落ちた場合もそれぞれ1行で出す
  - 掃き直しは、枠の余りが0なら待たずに止める（10/16 は8件を60秒待ってから0件で打ち切っていた）。投げる回数・枠の使い方は不変
  - 測り方（質問・モデル・回数・割当）は変えていない

---

## 2026-10-17／日次・月次・週次の観測と配信を一時停止（実験は継続）・停止中の実験の配分を毎日14本に

- **ダッシュボードの再設計のため、2026-10-17（土）から日次・月次・週次の観測と配信を一時停止（本田さん決定・再開日は未定）**。
  10/17 の日次（07:00）・実験（08:00）が走る前に入れた（02:00 JST に push）
  - 止める：日次観測7本（火・木・土）と毎日の結果の Slack 配信、月次観測12本、週次所見の生成と配信、prompt_marketing の Gemini
  - 続ける：**実験観測46本＋E37**・GA4／GSC の収集・各ワークフローの失敗通知（実験の失敗通知を含む）・この日誌と interventions.csv の記録、
    週次の drift_check・実験の週次集計
  - 停止は `config/observation_pause.yaml`（`paused_from: "2026-10-17"`）。再開は `paused_until` に最後の日を入れる
- **停止中の実験の Gemini：7日とも14本・予備6本（週98本）**。それまでは月水金日16本（予備4）・火木土11本（予備2）で週97本。
  日次・月次が止まって7日とも同じ配分になったため、前回検討した曜日別の案（A/B/C）は停止中は不要
  - 目標の週92本（46本×週2回）を満たす（週98本・各記事が週2回＋α）
  - **適用は 10/17 から。10/16 までの本数と巡回の割当は変えていない**（テストで固定）。10/17 の先頭の位置は変わらず、本数だけ 11→14
  - 予備は4本→6本。10/16 のような 503 の連続では、予備を使い切った後も取り直しが2本多くできる程度
  - 停止中は日次・月次の完了を待たない（待ちのジョブは「待つ必要がない」で終わる）
  - 1日の本数がアフター期間の途中で変わる（週97本→98本）。質問・モデル・記事の割当の順番は不変。判定（主指標 Gemini cited_article）の数え方も不変
- **再開時の注意**：火・木・土が11本に戻るので、14本×7日の前提は崩れる（14本の上限のままなら 14×4＋11×3＝週89本で92本を割る）。
  再開前に配分を決め直す。停止中の上限は停止中の日にしか効かないので、何もしなければ停止前の16本／11本（週97本）に戻る
- **時系列の切れ目**：日次の言及率・言及シェア・差分、月次観測、週次所見、prompt_marketing は停止期間の観測が0本になり、
  再開後と停止前は連続しない（欠測ではなく観測していない日）。実験と GA4・GSC の時系列は切れない
- interventions.csv I-34（停止）・I-35（停止中の実験の配分）に記録。README「観測と配信の一時停止」
- 同日追記：**Ahrefs の週次取得とシート（ahrefs_aio）への書き込みは、週次所見の停止から切り離して続ける**（GA4・GSC と同じく後から遡って取れないため・本田さん決定）。
  run_weekly.py は停止中も Ahrefs だけ取り、ルール・所見・Slack は止めたまま

---

## 2026-10-18／サイトの介入5件の記録と、組の正本（allocation_v1.csv）の確認

- **interventions.csv に5件を追記（I-36〜I-40）**。いずれも touches_pool46=no（46本の本文・46本へのリンクは不変）
  - I-36（10/16 11:12〜11:14・本田さん 管理画面）：固定ページ24本をゴミ箱へ（終了事業のサービスページ6本・資料ページ4本・サンクス13本・空の固定ページ1本）。
    現在404（2本は WordPress の自動推測で301）。公開ページから24本へのリンク0本（seo-agent 確認）。近い現行ページへの301を10本作る予定（転送先は46本以外で確認のうえ設定）
  - I-37（10/18 13:36・本田さん）：無料相談ページ（/service/btob-marketing-free-consultation/）とサンクスをゴミ箱から復元。下書きのため外からは404。公開に戻すときは別の行で記録する
  - I-38（10/18 13:05・seo-agent 9c）：トップページ「支援企業例」節のリード文を現在の事業に差し替え、事例カードを外した（scope=サイト全体）。46本へのリンクは前後とも0本
  - I-39（10/18 13:05・seo-agent 9c）：事例の分類名3つ（case_category 24・25・26）に「（提供終了）」を付けた。URL・本文は不変
  - I-40（10/18 13:40・seo-agent 9c）：ma-support-company のカテゴリを「BtoB MA導入・運用」から「BtoBマーケティング全般」へ。MA カテゴリは category-sitemap から消え、記事は post-sitemap に残る
  - アフター期間中の介入。判定レポートの交絡候補一覧（期間と重なる介入）に載る
- **組の正本の確認**：experiment_2x2/targets.csv（seo-agent の編集禁止リスト）の **group 列は 9/28 の割付より前の古い値のまま**で、
  46本中37本が allocation_v1.csv と違う。**組の正本は experiment_2x2/allocation_v1.csv（9/28 の割付）**
  - dashboard の全コードを検索した結果、targets.csv の group 列を読んでいる処理は無かった。targets.csv を開くのは
    allocate_47.load_articles（公開日 published 列のみ）だけで、凍結の一覧（experiment_freeze）は URL だけを読む
  - 判定・感度分析（summarize）、再ランダム化検定（rerandomize・summarize.randomization）、欠測の組別集計（experiment_weekly）、
    不均衡の確認・引用プローブはすべて allocation_v1.csv の組を使う（tests/test_allocation_source.py で固定）
  - 1か所だけ間接の経路を直した：ピラーの偏り（pillar.py・判定レポートの冒頭と6つ目の感度分析）は、seo-agent 側の表
    （pillar_existing_links／pillar_strong_overlap）の group 列を読んでいた。今の表は allocation_v1 と全行一致しているが、
    seo-agent が新しい表を出したとき古い組が入りうるため、割付表の組を使うようにした（割付表に無い記事だけ表の値）。判定の数字は変わらない
  - targets.csv は seo-agent 管理のため dashboard 側では直さない（group 列の更新は seo-agent 側の判断）

---

## 2026-10-18／targets.csv の group 列の削除に備えて、dashboard のテストを直した

- seo-agent 側で experiment_2x2/targets.csv の古い group 列（9/14 の48本版の仮の振り分けの名残）を削除する。その前に dashboard のテストを直した
- tests/test_allocation_source.py から、targets.csv に group 列があることや「37本が allocation_v1 と違う」ことを前提にした確認を外した。
  確かめる中身は「判定・感度分析・再ランダム化検定・欠測の組別集計・ピラーの偏りが allocation_v1.csv の組で数えること」だけ
  （割付表と違う組を別に与えても、結果がそちらに動かないことで確かめる）
- 「targets.csv に group 列が無いこと」を確かめるテストを1本追加。**seo-agent 側の削除が終わるまでは skip**（README「組の正本」に、削除したら skip を外すと書いた）
- **確認**：group 列を除いた targets.csv の写しを作り（本物は触らない）、テストの間だけ targets.csv の読み取りを写しに向けて全テストを実行 → 全件通過
  （1552 passed・targets.csv の読み取り43回を写しへ。skip 中のテストと同じ中身も写しで通過）。列がある今の本物でも全件通過（1551 passed）
- **seo-agent 側で group 列を削除してよい**（dashboard の判定・集計は影響を受けない）
- 同日追記：**seo-agent 側で targets.csv の group 列を削除した（ef5ff40）**。46本の URL・公開日・質問は不変（削除前と突き合わせて確認。変わったのは列と注記1行だけ）。
  「targets.csv に group 列が無いこと」のテストの skip を外した

---

## 2026-10-18／凍結46本のうち1本の誤情報修正への備え（感度分析の追加・ドリフト検知）

- **本田さん決定（案C）**：架空事例のうち、Perplexity が当社の実績として誤って紹介した「防災設備」の記事1本だけを実験期間中に直す
  （数字のある段落への架空の断りの追加と、数字を幅のある表現にする2点のみ）。残り38本は 2027-01-01 以降。experiment_flag は維持（除外しない）
- **感度分析に「誤情報修正1本抜き」を足した**（最後の行）。再ランダム化検定・早期解放ルールの条件(3)も同じ除外で数える
  - 既存の行との重なり：1本だけの集合なので、抜く記事がまったく同じになるのは features 抜き（その記事が agentforce-features のとき）だけ。
    そのときは1行にまとめる。9本・複数段落7本・ピラーの既存リンク先・リンク減2本に含まれるかは表の下に1行で出す。
    **どの記事かは seo-agent の記録待ちのため、重なりの確認結果は記録が届いてから書く**
- **週次のドリフト検知**：drift/expected_edits.json に修正前後の段落が入ると、その記事のその段落だけの変化を「想定内」として別枠に出す。
  段落の外が変わった・決めた内容と違う・戻した場合は「想定外」
- 判定レポートの交絡候補一覧：interventions.csv に scope=プール46本・touches_pool46=yes の行が入れば、先頭の組に載ることをテストで確認
- **記録が届くまでは、新しい行もドリフトの扱いも出ない**（感度分析の表の下に「記録待ち」と出る）。届いたら pool の1本・記事ID・
  expected_edits.json を埋め、interventions.csv に1行追記する

---

## 2026-10-18／誤情報修正1本の登録（agentforce-sales-roleplay・E33）

- seo-agent から記録が届いた（seo-agent 148d365）：**agentforce-sales-roleplay（post 7174・E33・②FAQのみ。allocation_v1.csv で確認）**。
  適用 2026-10-18 15:46:09 JST。本文195段落のうち数字のある26段落に架空の事例である旨の断りを入れ、数字を幅のある表現に変更
  （例：41% → 4割ほど、四半期18件 → 十数件）。見出し・リード・FAQ・リンク・タイトル・meta は不変（H3 見出しと FAQ の答えには元の数字が残る）
- **既存の感度分析との重なり：E33 は 9本（9/15〜16 追記）・features（訂正対象）・複数段落回答7本・ピラーの既存リンク先27本・リンク減2本の
  どれにも含まれない。** よって「誤情報修正1本抜き（E33）」は他の行とまとまらず、独立の8通り目になる
- pool.py に slug と E33 を登録し、感度分析「誤情報修正1本抜き（E33）」を有効にした。再ランダム化検定・早期解放の条件(3)も同じ除外
- interventions.csv に I-41 を追記（scope=プール46本・touches_pool46=yes）。判定レポートの交絡候補一覧の先頭の組（プール46本）に載る
- 判定レポートの冒頭に偏りの向きの注記を出す（短期・長期の両方）：②の引用が下がる場合、リードの効果は大きめ（甘い方向）、FAQの効果は小さめ。
  リードの早期解放は「誤情報修正1本抜き」でも効果の向きが同じときだけ通る
- ドリフト検知：drift/expected_edits.json に26段落の前後を入れた。seo-agent の公開 HTML の前後を drift_check と同じ形にして突き合わせた結果、
  差分は26段落と記事の「更新」の日付（2026-09-29 → 2026-10-18）だけ。日付の行は「適用日に変わった場合だけ」想定内として扱う。
  関連記事の並びは本文から切り落としているので出ない。10/12 の週次の基準は修正前の公開ページと一致しているので、10/19 の回は想定内の1本として出る見込み

---

## 2026-10-18／E33 の誤情報修正の訂正：FAQ の答え2か所も変えていた（I-42）

- seo-agent からの訂正報告（seo-agent feed64e）：agentforce-sales-roleplay（E33・②FAQのみ）は、本文26段落（15:46:09・I-41）に加え、
  **同日 16:05:54 に FAQ の答え2か所の数字も変更**していた（質問④ 41% → 4割ほど、質問② 2名ほど → 数名・営業20名 → 営業全員・10か月 → 1年近く）。
  本田さんの判断（FAQ も直す）。問いの数5・順番・位置は不変。apply_gate の例外は直後に外した。H3 見出しは変更なし
- **当初の条件と実際の範囲が違った**：決定時の条件は「数字のある段落1つ・2点のみ（断りの追加と数字の幅）」だったが、実際は
  本文26段落（I-41）と FAQ の答え2か所（I-42）。FAQ は B-24 の処置の対象（②は FAQ の組）なので、答えの文言の変更は②の処置の中身に触れる
- **感度分析は変えずに済む**：「誤情報修正1本抜き（E33）」は E33 を判定期間の全体から抜く方式なので、FAQ の修正も同じ1行で吸収される
- interventions.csv：I-41 の note の末尾に訂正を追記（既存の記述は残した）、I-42 を追記
- 判定レポートの注記を「本文26段落と FAQ の答え2か所を修正」に変えた
- ドリフト検知：expected_edits.json に FAQ の答え2か所の前後を入れた。seo-agent の公開 HTML（15:46 の後・16:05 の後）で確かめると、
  15:46 → 16:05 の差分は FAQ の答えの2行だけで、10/12 の基準（修正前）から見ても想定内。FAQPage の構造化データは `<script>` の中なので比べていない。
  ほかの FAQ の答え・決めた内容と違う答え・H3 見出しが変われば想定外になることをテストで確認

---

## 2026-10-18／並びによる誤引用の見張り（記録のみ）

- 制作管制の調査：架空の例（主語のない「ある会社では」型）の直後に「当社では…」が続くと、AI が当社の支援の例と読む（Perplexity の誤引用の原因）
- 凍結46本で同じ並びを持つのは E33（10/18 に修正済み・I-41／I-42）のほか、agentforce-mcp（E09・②）・agentforce-proposal-review（E47・④）・
  agentforce-sales-meeting（E42・①）の3本
- **並びによる誤引用のおそれがある凍結46本3本は 1/1 以降に修正。誤引用が確認されたらその1本だけ直し、感度分析に丸ごと抜く行を追加する**
- 実験の週次集計の参考欄に「5-2. 並びによる誤引用の見張り」を足した。4本の実験用プロンプトに対する実験の Gemini の回答で、
  社名（mentioned_v2 の表記）が出た件数（0件なら0件）と、出た回答の該当箇所（前後40字）を出す。組ごとの比較はしない（組の名前も出さない）。
  初回は 10/19（月）の週次（10/12〜10/18 の週）

---

## 2026-10-18／E33 の残りの修正（I-43）と時刻の訂正

- **取りこぼしの経緯**：10/18 15:46 の修正（I-41）は「数字のある段落」の差分案の26段落に限っていたが、防災設備の例はそれ以外にも
  13か所（FAQ の質問①を含む）あり、直した段落の中にも例の数字が残っていた。16:05 の FAQ の修正（I-42）も質問②・④だけだった。
  さらに、架空の例の直後に「当社では」が続く並び（誤引用の原因・制作管制の調査）が2か所残っていた
- **16:44:20（WordPress のリビジョン 9049・seo-agent 535f7d3）に残りを反映**：30か所（本文28・FAQ の答え2）。例の数字を幅のある表現にし、
  「当社では」が続く2か所は例の段落の終わりに「この例は説明のための架空の例で、当社の支援事例ではありません。」を足して分けた。
  回数・手順の数・体制の人数・記事が勧める数は残した。FAQ は数字だけ（問いの数・順番・位置は不変）。内部リンクは不変。interventions.csv I-43
- **時刻の訂正**：I-41・I-42 の時刻は、記録では保存の返事を受け取った時刻だった。WordPress のリビジョンの時刻は本文 15:46:07・FAQ 16:05:51。
  note に追記で訂正（description の 15:46:09・16:05:54 は消さずに残した）
- 感度分析は変えない（「誤情報修正1本抜き（E33）」の1行で I-41〜I-43 をまとめて吸収）。判定レポートの注記を
  「本文と FAQ の数字の修正、および架空の例と『当社では』の分離」を含む文にした
- ドリフト検知：expected_edits.json に30か所の前後を入れた。あわせて判定を厳しくした（前回の本文に決めた修正を順に当てた結果が今回と
  一字一句同じときだけ想定内）。行ごとの照合だけでは、分離の一文を消した変化を見逃すことがテストで分かったため。
  seo-agent の公開ページで、10/12 の基準（修正前）からも 16:05 の状態からも想定内、分離の一文を消す・数字を戻す・見出しを変えると想定外になることを確認
- 同日追記：I-42 の2点を note の末尾に追記で訂正（description は残した）。質問②の置き換えは「2名ほど → 数名」「営業20名 → 営業全員」「10か月 → 1年近く」の3つ。
  修正前後の全文は seo-agent の sales_roleplay_faq_applied_record_20261018.md（sales_roleplay_applied_record_20261018.md は本文26段落の記録）

---

## 2026-10-18／ピラーの本文だけの編集ではアフター期間を分けないことの確認

- ピラーA（agentforce-guide）が、凍結外の架空事例の数字の修正の2回目の反映（17:15:27）で変わった。数字の書き方だけで、46本へのリンクの本数は前後で同じ（seo-agent の最終確認待ち）
- 判定レポートの「ピラー編集の完了が 10/6 以降ならアフター期間を前後で分ける」仕組みを確認：完了日は pillar_links_added_*.csv の行だけから決まり、
  interventions.csv や WordPress のリビジョンは読まない。今の記録では完了は 10/3 で、短期・長期とも分けない
- **1か所直した**：表に add / remove 以外の行が混ざると add として数え、完了日が動く作りだった。add / remove の行だけを数えるようにした
  （本文の編集の行が表に入っても分けない。リンクを足した・外した行なら従来どおり分ける）。テストで確認
- 凍結外の修正の記録（前回の指示の1〜4）は、seo-agent の最終報告と渡し用の行が出るまで待つ

---

## 2026-10-18／凍結外の架空の例の直し（D-44）の記録（I-44〜I-46）

- 2026-10-18 17:14:12 E37（agentforce-coworker）の本文を修正（実験外・watch）
- seo-agent の渡し用の行（便UG 38行・便UJ 15行、seo-agent f7d908a）を、中身を変えずに output/handoff/ に写した
  （interventions_handoff_bunUG_20261018.csv・interventions_handoff_bunUJ_20261018.csv。元ファイルと同じバイト列であることを確認）
- interventions.csv にはまとめの3行で追記（53行は入れない）：
  - I-44：17:06:53〜17:25:30 凍結外37本（便UG）。site_content・touches_pool46=no
  - I-45：17:15:27 ピラーA（agentforce-guide）の断りの定型文に1文追加（リビジョン 9083）。ピラーA・touches_pool46=no
  - I-46：18:01:03〜18:05:26 凍結外15本の例と当社への言及の距離の解消（便UJ）。site_content・touches_pool46=no
- 写しで確かめたこと：53行の記事はどれも実験の46本に入っていない。46本へのリンクの本数・apply_gate NG0 は全行の note に記載。
  便UG の第1版は 17:06:53〜17:18:11、第2版は 17:13:54〜17:25:30（37本）。agentic-crm-abm-implementation-midsize は第2版だけ（第1版の行なし）
- 交絡候補一覧：判定期間（10/6〜）に I-44・I-46 が site_content、I-45 がピラーA として載る。プール46本に触れる行ではないので後ろの方に並ぶ
- ピラーA の行（I-45）でアフター期間は分かれない：ピラー編集の完了日は pillar_links_added の add/remove 行だけで決まり、今も 10/3（短期・長期とも分けない）
- 前の項目の訂正（追記）：ピラーA の変更は「数字の書き方」ではなく、断りの定型文に「当社の支援事例ではありません。」を足した1段落のみ（seo-agent の渡し用の行・リビジョン 9083）
- executor は届いたとおり「seo-agent（9c）」「記事制作」で書いた。seo-agent 側で正本のセッション（9d か 9c か）を確認中。誤りがあれば note に追記で訂正する

---

## 2026-10-18／executor の表記を sessionId に揃える（10/18 の行の訂正）

- 制作管制の確認：10/18 に cross-com.jp へ書き込んだのは、すべて1つのセッション（sessionId の先頭8文字 e0eede5c）だった。
  「9c」「9d」は Claude Code が起動のたびに自動で付ける表示名で、「9d」という名のセッションは存在しなかった（指示文の中の呼び名が記録に入ったもの）。並行する書き込みは起きていない
- interventions.csv の 10/18 の行で executor に 9c／9d を含む8行（I-38・I-39・I-40・I-41・I-42・I-43・I-44・I-46）の note の末尾に
  【2026-10-18 訂正】を追記（executor の列と既存の記述は変えない）。I-45 は executor が「記事制作」のため対象外
- 10/18 より前の行（10/2〜10/11 の 9d：I-21・I-22・I-23・I-26・I-31・I-32・I-33）は訂正しない。当時は実際に別のセッションが書き込んでいたことが確認されているため
- 今後の表記：executor のセッション名は sessionId の先頭8文字で書く（例：seo-agent（e0eede5c））。README の記録のルールに追記。
  seo-agent 側も R-92・CLAUDE.md に記載済み（seo-agent 4f3a54b・94b77b4 で確認）

---

## 2026-10-18／サイトへの書き込みの同時実行を止める印（site_write_lock）の導入（記録のみ）

- seo-agent（e0eede5c）の報告（seo-agent 91118bf・便UO）：
  - 10/18 の cross-com.jp への書き込み106件はすべて seo-agent（e0eede5c）。残る1件は本田さんの管理画面の自動保存（page 5706・18:42 以降・下書きで未公開）。
    page 9033 の下書き（14:45）も本田さん（未公開）
  - 便UG の第1版と第2版は 17:13:54〜17:18:11 に1セッションの中で並んで走っていた。最終が第2版にそろったのは順番と速さがそろっていたためで、仕組みで守られていたのではない
  - 再発防止として、サイトへの書き込みに実行中の印（site_write_lock）を導入。印があれば2つ目の書き込みは止まる。10/18 の状況を再現して止まることを確認済み。サイトの内容は変えていない
- interventions.csv には記録しない（サイトの内容の変化ではないため）
- page 5706・page 9033 の下書きは未公開のため記録しない。公開されたら、その時点で interventions.csv に記録する
- 件数の食い違い（未解決）：seo-agent の revisions_20261018.json の10/18 分107件には、page 9033 の下書き（リビジョン 9034・14:45:06）と page 5706 の自動保存（リビジョン 9125・18:42:30）の両方が入っている。
  この2件を本田さんの分とすると、seo-agent（e0eede5c）の分は105件で、報告の「106件＋1件」と合わない。seo-agent 側で確かめてもらう
  - **【2026-10-18 追記・解決済み】** seo-agent の照合（seo-agent 1a7fa7f・便UP）で確定：10/18 のリビジョン107件は seo-agent（e0eede5c）105件・本田さん（管理画面）2件（page 9033 の下書き 9034／page 5706 の自動保存 9125）・その他0件。
    先の「106件」は 107 から本田さんの2件を引き忘れた数え違い。revisions_20261018.json の「時間外」の印が全件に付いていたのは時刻の変換の取り違えが原因で、直した後は0件。
    修正後の revisions_20261018.json（writer 列）で 105件・2件・時間外0件を確認。interventions.csv は変えない（件数はどの行にも書いていない）
- I-45 の note に、書き込みは seo-agent（e0eede5c）の1セッションだった旨を追記した。指示の文にあった「10/18 の107件はすべて同じセッション」は、上の報告（107件には本田さんの分が含まれる）と合わないため、
  件数を入れずに「リビジョン 9083 は第2版 17:13:54〜17:25:30 の中の書き込み」とした

---

## 2026-10-21／凍結46本の事実訂正への備え（準備のみ・まだ反映していない）

- 本田さん確認の事実（2026-10-20）：Agentforce の顧客導入は0件。凍結46本のうち約20本に、導入実績があるように読める記述がある。
  当社実績の誤情報を止めるため、事実と違う文だけを近く直す（記事制作から一覧が届き次第、効果測定チャットで確認してから反映）。今回は判定側の準備だけで、サイトは変えていない
- 対象の表 `experiment_2x2/fact_corrections.csv`（E番号・slug・組・リビジョン・時刻）と、修正前後の文の表 `experiment_2x2/drift/fact_correction_sentences.csv`（E番号・slug・修正前・修正後）を見出しだけで作った
- 感度分析に2行：
  - A「事実訂正あり記事抜き（N本・全組）」：表の記事を判定期間の全体から組に関係なく抜く。既存の行と抜く記事の集合が同じならまとめる
  - B「事実訂正前で打ち切り（日時より前）」：アフター期間を全記事のうち最も早い訂正の時刻で切る（短期・長期の両方。timestamp を JST にして比べ、時刻の無い行は訂正の日を入れない）。
    訂正がアフター期間の後なら「両方込み」と同じなのでまとめる
  - どちらも再ランダム化検定をかけ、早期解放の条件(3)に含める。表が空のうちは「記録待ち」と出し、条件(3)には入れない（早期解放の欄に注記）
- 判定レポート：冒頭に「## 事実訂正」（組ごとの本数・差が3本以上で「偏りあり」・最も早い訂正の時刻・表の組と allocation_v1.csv の食い違い）。
  感度分析の表の下に、A で抜いた後の残りの本数（組ごと）と、B で使えるアフター期間の観測回数（全期間と並べる）
- ドリフト検知：時刻の入った記事は、前回の本文に決めた文の置き換えを当てると今回の本文と一字一句同じなら想定内（E33 と同じ考え方を文の単位で。分けて直した週も通る）。
  ほかが1字でも変われば想定外。表に載っているのに時刻か文が無い記事が変わったら想定外として「記録待ち」と注記
- 注意：**訂正を反映したら、判定の前に必ず2つの表を埋める**（空のままだと A・B が「記録待ち」のまま早期解放の条件(3)に入らない）。interventions.csv にも行を足す
- テスト：`tests/test_fact_corrections.py`（18件）。全体 1606件 pass

## 2026-10-21／サイトへの書き込みの正本の切り替えと、便VA の3件の記録

- **2026-10-21 から、cross-com.jp への書き込みの正本は seo-agent（a2846ad4）**（本田さんが sessionId で指定）。それより前は seo-agent（e0eede5c）。interventions.csv の executor もこの日から a2846ad4 で書く
- 便VA の3件を interventions.csv に追記（I-47〜I-49）。いずれも Agentforce の顧客導入0件（2026-10-20 本田さん確認）に合わせた事実の修正。凍結46本・保留14本に触れず、リンク先の増減なし（touches_pool46=no）
  - I-47　02:08:22 トップページ（page 83・リビジョン 9167）の Agentforce の文と支援企業のロゴの並び → scope=サイト全体
  - I-48　02:08:44 lab「Agentforceで商談の勝ち負けを分析」（lab_report 8991・リビジョン 9168）末尾の段落とリンクのアンカー → scope=site_content
  - I-49　02:09:06 導入支援会社8選（post 6102・リビジョン 9169）の表の新設・社名表記・当社紹介の文 → scope=site_content
- lab 8991 の末尾のリンクの先：公開ページ（REST の本文・更新 2026-10-21 02:08:44）で確認すると、記事内のリンクは目次のページ内リンクのほかは `/service/agentforce-support/`（固定ページ 5706）の1本だけ。**凍結46本の外**。I-48 の note に記録
- 交絡候補の一覧に3行とも載ることを確認（I-47 はサイト全体、I-48・I-49 は site_content）。テストに確認を追加
- 【2026-10-21 追記】I-47〜I-49 の description は効果測定チャットの要約の文面で、seo-agent の渡し用の行の原文ではなかった。description と既存の note は変えず、各行の note の末尾に【2026-10-21 追記・seo-agent の原文】として原文を追記。README の記録のルールに「渡し用の行が届いたら description・note は原文をそのまま使う。要約した場合は note に原文を追記する」を追加

## 2026-10-22／凍結46本の事実訂正（E22・E05）への準備（まだ反映していない）

- 近く、凍結46本のうち2本・3か所の事実訂正が入る（効果測定チャットで了承済み）：agentforce-reasoning-control（E22・③リードのみ）2か所、agentforce-roi（E05・③リードのみ）1か所。
  理由：Agentforce の顧客導入0件（2026-10-20 本田確認）なのに、当社が利用者から相談を受けている・顧客と一緒に作業していると言い切る文があったため。序文・見出し・FAQ・リンクは変えない。
  反映はその日の観測ジョブが終わった後（10:00 JST 以降の見込み）
- 10/20〜21 の準備の確認：fact_corrections.csv・感度分析 A・B・まとめ・早期解放の条件(3)・再ランダム化検定は**用意済み**（a2c3f0f）。足りなかった分を足した：
  - A の見出しを「事実訂正2本抜き（E22・E05）」の形に（表の E番号から作る）
  - 「## 事実訂正」に偏りの向きの注記（短期・長期の両方）：「E22・E05（ともに③）の本文3か所を事実訂正。③の引用が下がった場合、リードの効果は小さめ（安全側）、FAQの効果は大きめ（甘い方向）に出る」。組と向きは割付表から自動
  - 参考の表（反映の前後の Gemini の cited_article・mentioned_v2・観測回数。判定には使わない。冒頭に「2本・数回ずつの観測のため、上下から何かを言える量ではない」）。**11/2 の短期判定まで表は出さない**（組ごとの結果を途中で見ないルール）
  - ドリフト検知：修正前後の文を expected_edits.json の mode=sentences の項目で入れられるように（from が空なら fact_corrections.csv の訂正の日）。時刻が入るまでは想定内にしない
- 表はまだ空のまま（記録が届いたら fact_corrections.csv・expected_edits.json・interventions.csv〈届いた原文のまま〉に入れる）。テスト：`tests/test_fact_corrections_e22_e05.py`（12件）。全体 1618件 pass

## 2026-10-22／週次所見の凍結の検査（src/experiment_freeze.py）を 10/2 の凍結の縮小に追いつかせた

- 10/2 に凍結を統計46本だけに縮小した（ピラー2本 agentforce-guide・agentic-crm と agentforce-pricing は編集可。46本へのリンクの増減だけ不可・本田さん決定）。
  targets.csv・link_ban.csv は seo-agent 側で46本に書き換わったが、**dashboard のコードは「ピラーは編集の動詞があるときだけ違反」の規則とプロンプトの文（「ピラー:張り先にするのは可」）が 49本の頃のまま残っていた**。
  実ファイルからピラーが外れていたので、実際の所見でピラーの編集が差し替えられたことはない（規則が使われない状態だった）。テストも 49本の頃の凍結を固定して確かめていた
- 直したこと：
  - 違反として差し替えるのは、統計46本（targets.csv）に触れる提案だけ。ピラー2本・pricing への編集の提案は違反にしない（`config/experiment_freeze.yaml` に `unfrozen_pages`・`pillars` を追加）
  - ピラーの提案に「46本へのリンクを足す・外す」が含まれるときだけ、注意（違反ではない）をジョブサマリの警告に出す。文に「46本へのリンクの増減は apply_gate が書き込み時に止める」と書く。その行でも46本そのものを編集する書き方なら違反
  - プロンプトに「2026-10-02 に凍結を解いた（編集してよい）。ただし凍結対象へのリンクを足す・外すことはしない」を渡す
  - テスト：ピラーの本文の編集→違反にならない／ピラーから46本へのリンクを足す・外す→注意／46本への編集・リンク→これまでどおり違反／2027-01-01 以降はどれも出ない。README の 2-4 を書き換え

## 2026-10-22／E22・E05 の事実訂正の反映の記録（便VC）

- seo-agent（a2846ad4）が反映：観測ジョブ 2026-10-22 の完了（dashboard afc3e8f・10:20:15 JST）を 11:29:43 JST に確認してから、
  **E22 agentforce-reasoning-control（post 6648・③）を 11:29:46 JST にリビジョン 9190**（2か所を1回で保存）、**E05 agentforce-roi（post 6647・③）を 11:30:10 JST にリビジョン 9191**。
  apply_gate の例外（この2記事・この3か所・当日だけ）は 11:30:16 に外れた
- 公開ページで変わったのは3か所と更新日の表示（2026-09-29 → 2026-10-22）と dateModified だけ。序文・見出し・FAQ・マーカー・画像・段落の数・タイトル・状態・抜粋は不変。
  46本へのリンクは 6648 が 8→8、6647 が 6→6（同じリンク先）。E05 の序文1文目は今回直さず 2027-01-01 のバッチへ
- 記録したもの：
  - `experiment_2x2/fact_corrections.csv` に2行（E22・9190・2026-10-22 11:29:46／E05・9191・2026-10-22 11:30:10）。感度分析 B の区切りは早いほうの 2026-10-22 11:29:46。
    10/22 朝の観測（最後が 10:15:42 JST・ジョブ完了 10:20:15）は区切りより前（修正前）に入る（テストで確認）。B の見出しを秒まで出す形に変更（「…11:29:46 より前」）
  - `experiment_2x2/drift/expected_edits.json` に3か所の修正前後（一字一句・mode=sentences）。更新日の表示は反映日（2026-10-22）に変わった場合だけ想定内。dateModified は構造化データなので本文の比較に入らない。
    実際の週次スナップショットに置き換えを当てて、想定内（10/22 の日付）・想定外（ほかの日付・反映日より前）になることをテストで確認
  - `output/interventions.csv` に I-50・I-51（E22）・I-52（E05）を届いた原文のまま追記。原文の4列目（URL）は scope の位置に入っていたので、scope は「プール46本」、URL は note の先頭に「対象：〈URL〉。」として移した（README の記録のルールに追加）
- 判定レポートで確認：「## 事実訂正」が記録待ちから本文の注記（E22・E05 ともに③・3か所・偏りの向き）に切り替わった。感度分析 A「事実訂正2本抜き（E22・E05）」と B「事実訂正前で打ち切り（2026-10-22 11:29:46 より前）」が計算される
  （今のアフター期間の観測はすべて区切りより前なので、B は「両方込み」と同じ観測としてまとまる）。参考の表は 11/2 まで数字を出さない。交絡候補の一覧（プール46本）に I-50〜I-52 が載る
- 既存のテストのうち「誤情報修正1本抜きが末尾」「感度分析が8通り」などを、事実訂正2本抜きが末尾に付く形（9通り）に直した

## 2026-10-22／11/2 より前は組ごとの数字を出さない仕組み

- **2026-10-22 確認作業で本物のデータの判定を実行し、組ごとの数字が Claude Code の画面に一度出た。誰にも渡しておらず、判断にも使っていない。以後、11/2 より前は組ごとの数字を出さない仕組みにした**
  - 実行したのは E22・E05 の記録の確認（「## 事実訂正」の注記と感度分析 A・B が計算されるか）のため。短期（10/06〜11/01）・長期（10/06〜12/27）の2本
- 仕組み（`experiment_2x2/summarize.py`）：本物のデータで実行したとき、2026-11-02 00:00 JST より前は組ごとの数字（組別の率・差・p値・感度分析の表・早期解放の判定・参考の表）を計算も表示もしない。
  見出し・注記・「短期判定まで出さない」・46本全体の数字・観測の無い記事の組別本数だけを出す。日付は実行した時刻（JST）で決め、引数・環境変数では前倒しできない。
  作り物のデータかどうかは読み込むファイルの場所（pytest の一時フォルダか tests/ の下）で決める。仕組みを入れたあと、本物のデータでは見出しと「出さない」の表示の有無だけを確かめた（中身は見ていない）
- 残っていないかの確認：判定の出力を書いた Claude Code の作業用フォルダ（scratchpad）のファイル3つ（short.md・rep_2026-10-06_2026-11-01.md・rep_2026-10-06_2026-12-27.md）を、中身を開かずに削除した。
  リポジトリの output/・experiment_2x2/results/・data/ とコミットには残っていない（summarize.py はファイルを書かない）。Claude Code のこのセッションの会話記録（ローカルの .jsonl）には画面に出た分が残っている
- 今後、判定の出力を確かめるテストや作業は、作り物のデータか、見出しの確認だけで行う（README に明記）。テスト：`tests/test_group_blind.py`

## 2026-10-22／Claudeforce 記事の引用回数の確定と、新記事・指名検索の記録運用（戦略管制塔の依頼）

- 戦略管制塔が 10/14 に出した依頼が dashboard 側に届いていなかったもの。10/22 に受け取って対応。**実験46本の判定には一切使わない参照データ**
- **Claudeforce 記事（https://cross-com.jp/claudeforce/・post 8224）の引用回数：0回**
  - 対象：2026-09-23〜10-20 の Gemini の全行。llm_experiment 380行（28日）・llm_marketing 56行（10/02・10/08 の2日。10/17 から一時停止）と、同じ範囲の raw 436ファイル
  - 探した場所：引用元（cited_domain・cited_domains）・raw の引用URL（raw_cited_urls・unresolved_redirects）・リダイレクト解決後のURL（cited_urls）。llm_marketing のタブには URL の列が無いので、ドメインと raw で確かめた。出た行は無し
  - 観測している質問（実験46本・第3観測層57本）に Claudeforce を直接聞く質問は含まれていないため、0回は観測の設計上自然
  - 9/17 の観測で Claude の回答本文に出た「Claudeforce」は、サービス名として出ただけで記事の引用ではない
  - 確認は該当行の有無と行数だけを出す形で行い、組は表示していない
- **新記事公開の記録運用**：新記事が公開されるたびに interventions.csv に scope=new_article で1行（README に形式）。公開の情報は seo-agent 側の渡し用の行で受け取る
  - Claudeforce 記事（2026-09-23 公開）を I-53 として記録。46本の実験用プロンプトに答えうるかは**要確認**（seo-agent の 10/02 の重なりの判定は「弱」で E番号の記録が無い。強の重なり13本には含まれない）。公開したセッションの sessionId も未確認。seo-agent に E番号と sessionId を確かめてもらう
  - 判定レポートの交絡候補一覧の直後に「新記事の横取りのおそれ」を追加：判定期間の新記事の本数、答えうる本数と E番号、要確認の本数。組ごとの本数は 11/2 の短期判定から。交絡候補一覧に scope=new_article の行が載ることもテストで確認
- **指名検索の月次記録**：`output/brand_search_monthly.csv` を新設（数字は本田さんが GSC で手作業で取得）。定義（①正規表現全体は件数のみ・②「合同会社クロスコム」・③「クロスコム」）と「1〜数件の差で傾向は判断しない」を README に記載
  - 2行を記録：2026-08-22〜09-18（28日・①クリック25・表示97）と 2026-09-23〜10-19（27日・①19・97、②11・16・1.0、③7・38・2.6）。9/18 基準の開始日 8/22 は依頼文による（リポジトリに取得期間の記録が無く照合していない）
- テスト：`tests/test_new_article.py`

## 2026-10-22（続き）／第3観測層（llm_marketing）の 10月の Gemini が2本しか入らなかった件の確認

- **訂正**：上の項（Claudeforce 記事の引用回数）の「llm_marketing 56行（10/02・10/08 の2日。10/17 から一時停止）」は不正確だった。
  56行のうち答えが返った観測は **10/02 の2本だけ**（10/02 は4本投げて2本が 503）。10/08 の52行は停止ルールで投げていない quota_skipped。
  また10月分の期間（1〜14日）は 10/14 で終わっており、10/17 からの一時停止は10月分には関係しない。README の記述も直した。Claudeforce 記事の引用0回は変わらない
- **10月の Gemini の予定と実績**（予定＝その日の計画の消費を20から引いた残りが3回以上の日の本数。実績は raw。GitHub Actions のログは手元に gh が無く読めなかったため、
  raw・実験日誌・コミットの記録と run_marketing.py の判定を同じ関数で再現して確かめた）

  | 日 | 予定 | 実績 | 理由 |
  |---|---|---|---|
  | 10/01（木） | 0 | 0 | 日次・月次バッチB・実験で枠を使い切る（実消費20） |
  | 10/02（金） | 4 | 4（答え2・503 2） | 1本1回で取り直さない設計のため 503 の2本はそのまま |
  | 10/03（土） | 0 | 0 | 日次7＋実験11＝18（残り2） |
  | 10/04（日） | 4 | 0 | 実験の取り直し2回で実消費18（残り2） |
  | 10/05（月） | 4 | 0 | 実験のジョブが Gemini の応答待ちで4時間の制限に掛かり打ち切られ、marketing の段まで進まなかった |
  | 10/06（火） | 0 | 0 | 日次7＋実験11＝18 |
  | 10/07（水） | 0 | 0 | 月次バッチA 6＋実験14＝20。この日の実験の E18 が 429 PerDay |
  | 10/08（木） | 0 | 0 | **停止ルールが働き、残り52本を quota_skipped**（10/07 E18 がきっかけ・日誌に自動記録） |
  | 10/09（金） | 4 | 0 | 停止済み |
  | 10/10（土） | 0 | 0 | 停止済み（実験で 429 PerDay がさらに2件） |
  | 10/11（日） | 4 | 0 | 停止済み |
  | 10/12（月） | 4 | 0 | 停止済み（実験の取り直しで実消費20だったため、止まっていなくても0本） |
  | 10/13（火） | 0 | 0 | 停止済み |
  | 10/14（水） | 4 | 0 | 停止済み。10月の期間の最終日 |
  | 計 | 28 | 4（答え2） | |

- **10/17 からの一時停止**：本田さんの決定（ダッシュボードの再設計のため・2026-10-17 02:00 JST に push）。`config/observation_pause.yaml` の `paused_from: "2026-10-17"`。
  日次・月次・週次と同時に prompt_marketing の Gemini も止める。10月分は 10/14 で期間が終わっていたので影響なし
- **11月第1週は、今の設定のままでは再開しない**：`paused_until` が空（再開日未定）のため、11/1〜14 も「停止中」で何もしない。PerDay 欠測による停止は月ごとに数え直す（10月の停止は持ち越さない）
- 直すかどうかは本田さん・戦略管制塔の判断待ち（設定・コードは変えていない）

## 2026-10-22（続き）／I-53 の確認結果の追記と、第3観測層の10月分の停止の記録

- **I-53（Claudeforce 記事）**：seo-agent（a2846ad4）の確認を note の末尾に原文のまま追記（既存の記述と executor の列は変えていない）。
  重なりは強0・弱（E16・E22・E14・E46・E11・E12）。公開は 2026-09-23 00:20:51 JST（リビジョン 8229）、セッション 5efdb82d（便JM・R-92 の正本指定より前）
  - 判定レポートの「新記事の横取りのおそれ」を、note の「実験用プロンプトとの重なり：」から強・弱を読む形に変えた。本物のデータで表示が
    「強0・弱（E16・E22・E14・E46・E11・E12）」になり、組は出ないことを確認（11/2 から強・弱それぞれの組ごとの本数を出す）
- **第3観測層の10月分**：9/26 の条件④（実験の観測で PerDay の欠測が1回でも出たら、その月の残りの prompt_marketing を停止）は**働いていた**
  - きっかけ：**2026-10-07 11:19:31 JST の実験の E18**、`429 RESOURCE_EXHAUSTED`（quotaId `GenerateRequestsPerDayPerProjectPerModel-FreeTier`）
  - 停止：**2026-10-08 11:29:33 JST**（その日の実験の観測のあとの prompt_marketing の段）。残り52本を quota_skipped。**10月分は取り直さない**
  - 予定と実績の表は上の項（10月の予定は最大28本、投げたのは 10/02 の4本・答え2本）
- **10/17 からの一時停止**：本田さんの決定（ダッシュボードの再設計のため・2026-10-17 02:00 JST に push・`config/observation_pause.yaml` の `paused_from`）。
  10月分の実行期間（1〜14日）は 10/14 で終わっており、10月分には関係しない
- **11月第1週は通常どおりには動かない**（設定は変えていない）：`paused_until` が空（再開日未定）のため、11/1〜14 も「停止中」で何もしない。
  通常どおり動かすには、本田さんの判断で一時停止を解く（`paused_until` に最後の日）か、prompt_marketing の Gemini だけを一時停止から外す

## 2026-10-22（続き）／第3観測層の Gemini を一時停止から外す・実験の観測の確認・9/18 基準値の期間の訂正

- **実験の観測は一時停止の対象外（確認）**：`run_experiment.py` は `observation_paused` を呼ばない。停止中に変わるのは1日の本数だけ（`settings.experiment_daily_count` が14本）。
  experiment.yml にも停止で実験を飛ばす条件は無い。10/17 以降の llm_experiment の Gemini（本数・欠測だけを数えた）：

  | 日 | 予定 | 行（raw・シートとも） | 欠測 | E37（watch） |
  |---|---|---|---|---|
  | 10/17 | 14 | 14 | 0 | なし（予定なし） |
  | 10/18 | 14 | 14 | 0 | なし（予定なし） |
  | 10/19 | 14 | 14 | 0 | あり |
  | 10/20 | 14 | 14 | 0 | なし（予定なし） |
  | 10/21 | 14 | 14 | 0 | なし（予定なし） |
  | 10/22 | 14 | 14 | 0 | あり |

  テストで固定：停止中（対象外の設定あり）でも実験は毎日その日の計画どおり14本を投げる
- **第3観測層の Gemini を一時停止の対象外に（本田さん決定・interventions I-54）**：`config/observation_pause.yaml` に `exempt: [marketing_gemini]`。
  `settings.observation_paused(date, job=...)` が対象外の観測だけ False を返す（書ける名前は `settings.PAUSE_EXEMPTABLE` だけ。知らない名前は止める）。
  日次・月次・週次所見と prompt_marketing の Claude は停止のまま。実験優先・1日20回・1分あたりの間隔・層ブロック順・毎月1〜14日・条件④は変えていない
  - 11月の予定（取り直しが無い場合）：11/1〜11/9 は実験14＋marketing 6＝20、11/10 は14＋3＝17、11/11〜14 は14＋0（予備）。57本は 11/10 に終わる。
    PM-L1-19〜21（IT研修業界3本）は MOFU_L1 の末尾で 11/9 に届く。表は README
  - 10/23〜10/31 は10月の期間外で、10月分は 10/08 に閉じているので何も投げない
- **9/18 基準値の期間の訂正**：本田さんが GSC で確認し、基準の期間は 2026-08-20〜2026-09-16（28日）。8/20〜9/16 は今クリック25・表示96（表示の1件差は GSC の後からの数値の直し）、
  8/22〜9/18 はクリック24・表示101で不一致。`output/brand_search_monthly.csv` の1行目は消さず note に訂正を書き、訂正の行を末尾に足した

## 2026-10-22（続き）／ダッシュボード作り直しの間、観測の実行と記録を変えない決まり（戦略管制塔との決まり）と、その見張り

- **決まり（2026-10-22・戦略管制塔と）**：ダッシュボードの作り直しは表示の部分のみ。観測の実行と記録は、長期判定（12/28 の週）が終わるまで変更しない。
  変更が必要な場合は、事前に効果測定チャットと管制塔へ相談する
- **変えてはいけないもの（19件）**：`.github/workflows/experiment.yml`・`src/run_experiment.py`・`src/collect_llm.py`・`src/experiment.py`・
  `config/prompts_experiment.csv`・`config/prompts_watch.csv`・`experiment_2x2/allocation_v1.csv`・`config/experiment_job.yaml`・`config/observation_pause.yaml`・
  `config/claude_budget.yaml`・`src/claude_budget.py`・`src/force_log.py`・`src/run_marketing.py`・`.github/workflows/marketing.yml`・`config/prompts_marketing.csv`（以上ファイル全体）、
  `src/settings.py`（観測計画・枠・間隔・再試行・時間の予算・観測順の輪・一時停止・Claude の停止の関数と定数）・`src/sheets_writer.py`（llm_experiment・llm_marketing への書き込み）・
  `src/marketing.py`（第3観測層の実行の関数）・`src/retired_urls.py`（転送URLの解決）は関数・定数の単位。一覧は README と `config/observation_lock.yaml`
- **見張り**：`config/observation_lock.yaml` に今の中身の SHA-256 を記録。`tests/test_observation_lock.py` が違いを見つけたら決まりの文で失敗する。
  2027-01-04 以降は飛ばす。承認された変更は `python src/observation_lock.py --update --reason "承認の経緯"` で、ハッシュ・history・この日誌を同じコミットで更新する
  （ハッシュの更新だけのコミットは作らない）
- 一時停止の解除（`paused_until`）も一覧に入る（実験の1日の本数が変わるため）。解く前に相談する
- **欠測の注記**：判定レポート（summarize.py）に「観測の欠測」を足した。日ごとの計画と答えの取れた行を突き合わせ、抜けた日の日付・本数・理由を自動で出す
  （理由は実験日誌 → error 列。どちらにも無ければ「記録なし」）。作り物のデータでテスト。組は出さない。
  本物で確かめた結果（日付と理由だけ。ビフォー 9/15〜9/28・アフター 10/06〜）：9/19 枠切れ10本、10/07 枠切れ1本・503 4本、10/10 枠切れ2本、10/16 503 8本。
  最初は 9/20・9/21 に「記録なし」各2本が出たが、今の計画（月水金日16本）で数え直したための誤り（16本の上限は 9/21 13:25 から。その2日の朝は14本の決まりで動いた）。
  9/22 より前の日は記録のある欠測だけを数えるように直した

## 2026-10-22（続き）／観測に使うライブラリの版の固定と見張り

- **調べ方**：GitHub Actions の実験ジョブ（experiment.yml）の Install dependencies のログを、9/15〜10/22 の38回分すべて読んだ。
  prompt_marketing の Gemini も同じジョブで走るので同じ版。marketing.yml（Claude）は停止中で、直近の実行（10/22 14:34）はインストールの段まで進んでいない
- **固定した版（直近の実行＝2026-10-22 10:09 JST・run 39704011106 と同じ版）**：`google-genai==2.32.0`（Gemini の呼び出し）・`gspread==6.2.1`（シートへの書き込み）・
  `google-auth==2.62.0`（シートの認証）・`requests==2.34.2`（引用URLの転送先の解決）。ほかのパッケージは今のまま（下限だけ）
- **今の動きが変わらないことの確認**：4つとも 10/21・10/22 の実行で入っていた版と同じ。固定した requirements.txt を pip で試しに解決すると、
  4つとも同じ版、`httpx` 0.28.1・`google-api-python-client` 2.201.0 も 10/22 の実行と同じになった（試しの解決は手元の Python。Actions は 3.12）
- **見張り**：`config/observation_lock.yaml` に requirements.txt の4行だけを足した（20件目。ほかの行の追加・変更、固定した行のコメントでは失敗しない）。
  上げる必要が出たら（セキュリティの更新を含む）、事前に効果測定チャットと管制塔へ相談してから上げる
- **固定する前の版の動き（記録）**：`google-genai` は実験の途中で上がっていた。9/15 2.23.0 → 9/17 2.24.0 → 9/23 2.25.0 → 10/01 2.26.0 → 10/02 2.27.0 → 10/03 2.28.0 →
  10/08 2.29.0 → 10/13 2.30.0 → 10/14 2.30.1 → 10/15 2.31.0 → 10/21 2.32.0。ビフォー（9/15〜9/28）は 2.23.0〜2.25.0、アフター（10/06〜）は 2.28.0〜2.32.0。
  `google-auth` は 2.58.0 → 2.62.0。`gspread` 6.2.1・`requests` 2.34.2・`httpx` 0.28.1 は 9/15 から変わっていない。
  同じ日の観測は4組とも同じ版で取っているので、版の違いは4組に同じようにかかる

## 2026-10-22（続き）／Claudeforce 記事の更新の記録（便VG・I-55）

- **渡し用ファイル**：seo-agent（a2846ad4）の `crosscom-seo-agent/output/reports/bunVG/interventions_handoff_bunVG_20261022.csv` を
  `output/handoff/` にそのまま写した（1,075バイト・SHA-256 8c151625…1cac1c で一致）
- **照合**：渡し用の行は依頼の要点と一致（2026-10-22 17:48:42 JST・リビジョン 9212・post 8224 claudeforce・D-45 への部分的な合わせ込み・①〜③・タイトルと見出しは変更なし・
  本文から46本へのリンク 0→0・touches_pool46=no・executor seo-agent（a2846ad4））
- **I-55 として追記**：説明・executor・touches_pool46 は原文のまま。原文の scope の列は URL（https://cross-com.jp/claudeforce/（post 8224））なので、
  I-50〜I-52 と同じ扱いで scope=site_content とし、URL は note の先頭に「対象：〈URL〉。」として移した（凍結46本の外）
- **I-53 の note に追記**：「2026-10-22 17:48:42 に本文を更新（I-55）。46本の質問への答え方（強0・弱 E16 ほか）を変える変更ではない」。重なりの読み取り（強0・弱6本）は変わらない
- **交絡候補一覧**：判定レポートの「判定期間中のサイト施策一覧」の site_content に I-55 が載ることを確認（アフター期間 10/06〜11/01 の中）

## 2026-10-22（続き）／Gemini のライブラリの版の変化が、引用の取り出しに影響していないかの確認

- **版が変わった日（10回。前回の報告で「9回」と書いたのは数え違い。ログでは10回）**：9/17 2.24.0・9/23 2.25.0・10/01 2.26.0・10/02 2.27.0・10/03 2.28.0・10/08 2.29.0・
  10/13 2.30.0・10/14 2.30.1・10/15 2.31.0・10/21 2.32.0（9/15〜16 は 2.23.0）。各版の観測（答えの取れたプール46本の行）：
  2.23.0 2日22本・2.24.0 6日60本・2.25.0 8日111本・2.26.0 1日3本・2.27.0 1日15本・2.28.0 4日45本・2.29.0 5日66本・2.30.0 1日11本・2.30.1 1日16本・2.31.0 6日74本・2.32.0 2日27本
  （版は観測した時刻の日付の実験ジョブの版。10/05 はジョブが時間切れで行が無い）
- **ビフォー・アフターの版**：ビフォー（9/15〜9/28）は 2.23.0〜2.25.0、アフター（10/06〜）は 2.28.0〜2.32.0。2.26.0・2.27.0 は期間の間の 10/01・10/02 だけ
  （依頼文の「ビフォー 2.23.0〜2.27.x」は実際と違うので、注記は実際の版で書いた）
- **確認（46本をまとめた全体のみ。組・cited_article・mentioned 系は計算も表示もしない）**：`experiment_2x2/genai_version_check.py`。
  日ごとに、引用元のある行の割合・1行あたりの引用元の数・grounding が空の行の割合を出し、版が変わった日の前3日・後3日の差を、
  版が変わっていない日の境目の差の最大（ふだんの揺れ）と比べた。**結果：段差なし（10日とも）**。表は `output/reports/genai_version_check_20261022.csv`
  - 最初の見方（ならす前の差）では 10/21（2.31.0→2.32.0）だけが揺れを超えた。grounding が空になる行は46本のうち12本の記事に偏っていて、
    空になりやすい記事が 10/18〜20 に6本固まり、10/21〜22 は1本だけだったため。10/21〜22 に観測した記事は、それより前も空がほとんど無い。
    各行から記事ごとの平均を引いて記事の違いをならすと、10/21 も揺れの範囲。ビフォーとアフターの全体の水準の差も、ならした値でふだんの揺れより小さい
  - 段差が無かったので、google-genai のリリースノートの確認（依頼の3）はしていない
  - 引用元が無い行と grounding が空の行は同じ行だった（取り出した引用元URLが無い行は、転送先の解決後も引用元が無い）
- **判定レポートの注記**：「Gemini のライブラリ（google-genai）の版」の項を足した（短期・長期の両方）。依頼の文面の「差の差では打ち消される」は、
  11/2 より前の表示の見張り（「差の差」の語を出さない）に掛かるので「前後の変化を組どうしで比べる判定では打ち消される」と書いた
