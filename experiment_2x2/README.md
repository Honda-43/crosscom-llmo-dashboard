# LLMO 引用観測プローブ（自前計測）

> **プローブは実験期間中は不使用。判定は llm_experiment のみ。**（2026-09-22 決定）
> 実験期間（〜2026-12-31）は、このプローブで観測しない。処置の効果の判定は dashboard の
> `llm_experiment`（Gemini・Claude の実験観測）だけで行う。Perplexity は使わない。
> 既存の結果（`results/2026-09-17.csv`）も判定・裁定のどちらにも使わない。

Ahrefs の記事単位の引用データは Lite プランの API では取得できないため、
自前で「同じ質問を同じモデルに投げ、引用URLを記録する」観測として作ったもの。
実験期間中は止めてあり、以下は実験後に使うときのための記録。

## 止めている仕組み
- `.github/workflows/probe.yml` は自動実行（schedule）を外してある。手動で起動しても、
  2026-12-31 までは観測せずに終わる
- `llmo_probe.py` は鍵の無いモデルを外し、観測できるモデルが無ければ結果ファイルを作らない。
  既定のモデルに Gemini は入れていない（dashboard と同じ `GEMINI_API_KEY` の無料枠を食うため）

## 対象と質問文（実験後に使う場合）
- 対象と質問文は `config/prompts_experiment.csv`（プール46本。2026-09-22 に E37 を除外）の
  `prompt` 列。組は 9/28 の割付の結果 `allocation_v1.csv`（`allocate_47.py --write` が書く）から引く。
  `targets.csv` は編集禁止リスト（49本）で、観測には使わない。プールの定義は `pool.py`
- 組別の集計は `probe_summary.py`（Perplexity の cited_article 率。参考）
- 費用の参考（2026-09-22 時点の Perplexity sonar 料金）：46本×3回=138回で約 $0.8

## ビフォー（基準値）の扱い
- **2026-09-17 の観測（`results/2026-09-17.csv`・144行・Claude のみ）は使わない。**
  9/22 に質問文を `targets.csv` の `query` から `config/prompts_experiment.csv` の `prompt` に
  切り替えたため、46本すべてで質問が異なる（`pool.PROBE_BASELINE_EXCLUDED`。
  `probe_summary.py`・`summarize.py` はこの回を読まない）
- 処置反映日と反映後1週間の結果は使わない（反映ラグ）

## 割付（allocate_47.py）
- **既定はドライラン**（画面に出すだけ）。`--write` を付けたときだけ `allocation_v1.csv` と
  `output/reports/experiment47_allocation_v1_20260928.md` を書く
- `--write` は **9/28 の本番実行の1回だけ**。9/28 より前は `--write` を付けても止まる。
  割付表は seo-agent の apply_gate が 9/29〜30 の処置の通し判定に読むので、本番前に書かない

## 判定（summarize.py）
- 判定は **llm_experiment のみ**。既定でシートの llm_experiment を読む：
  ```
  python3 experiment_2x2/summarize.py --before 2026-09-15:2026-09-28 --after <開始>:<終了>
  ```
  （`--csv` でシートの書き出しを使える。`--model gemini|claude` で1モデルだけ）
- `experiment_flag=watch` の行（E37）・プール外・欠測の行は自動で数えない
- 鮮度更新の訂正対象2本（agentforce-vibes・agentforce-features）の **2本込み／2本抜き** を
  モデルごとに出す。組は `allocation_v1.csv` から引く（割付前は止まる）
- `--probe results/<アフター>.csv [results/<ビフォー>.csv]` はプローブの結果での集計（参考。実験期間中は不使用）

## 指標
- cited：その記事URLが引用されたか（1/0）
- site_cited：cross-com.jp のどれかのページが引用されたか（推奨数の代理・枝②用）
- 記事ごとの「1回でも引用された」を記事単位の引用率の分子にする
