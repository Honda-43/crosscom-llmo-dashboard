# LLMO 引用観測プローブ（自前計測）

Ahrefs の記事単位の引用データは Lite プランの API では取得できないため、
自前で「同じクエリを毎週同じモデルに投げ、引用URLを記録する」観測を行う。

## セットアップ
1. `targets.csv` の `query` 列に、各記事の主キーワードを自然文の質問にして記入する
   （例: 「Agentforceの料金はいくらですか」）。KWマスターの主KWを使う。全48行を埋める。
2. 環境変数を設定（使うものだけ）
   ```
   export ANTHROPIC_API_KEY=...
   export PERPLEXITY_API_KEY=...
   export GEMINI_API_KEY=...        # 任意
   ```
3. 実行（ビフォー観測は処置反映の前に必ず1回）
   ```
   python3 llmo_probe.py --runs 3 --models claude,perplexity
   ```
   `results/YYYY-MM-DD.csv` に記録される。

## 運用
- 毎週月曜、同じコマンドを実行する（同じクエリ・同じモデル・同じ回数）。
- 処置反映日と反映後1週間の結果は判定に使わない（反映ラグ）。
- 判定：`python3 summarize.py results/<アフター最終日>.csv results/<ビフォー>.csv`

## 指標
- cited：その記事URLが引用されたか（1/0）
- site_cited：cross-com.jp のどれかのページが引用されたか（推奨数の代理・枝②用）
- 記事ごとの「1回でも引用された」を引用率の分子にする（summarize.py が集計）
