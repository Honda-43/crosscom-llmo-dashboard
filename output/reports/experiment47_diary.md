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
