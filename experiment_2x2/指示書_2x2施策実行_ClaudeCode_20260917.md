# 指示書：2×2 引用実験 施策実行（Claude Code 用）

作成日：2026-09-17　実験ID：EXP-2x2-01

## 0. この指示書の目的
結論要約リード文とFAQブロック化が、AI回答への引用を増やすかを検証する2×2実験の「処置反映」を行う。
**この指示書の範囲は、指定URLへの指定処置の適用のみ。** 品質改善・リライト・内部リンク追加・タイトル変更は範囲外であり、行った時点で実験は無効になる。

## 1. 絶対ルール（違反は実験の失敗）
1. ①対照群の12本には**一切触らない**。閲覧はよいが、保存・更新をしない。
2. ②③④の各記事には、**指定された処置だけ**を適用する。処置以外の箇所（本文・見出し・メタ・画像・内部リンク・カテゴリ・タグ）は変更しない。
3. 48本すべての処置を**同一日**に反映する。日をまたぐ場合は、その日の作業を開始前に報告し、指示を待つ。
4. 各記事の更新日（modified）が処置反映日になることは許容する。ただし本文中の「更新日」表記は変えない。
5. 処置内容の「良し悪し」を判断して手を加えない。仕様どおり機械的に適用する。迷ったら止めて報告する。
6. 作業前に各記事の本文を全文バックアップ（WordPress リビジョンで可）。

## 2. 処置の定義

### 処置L：結論要約リード文
- 位置：記事本文の最上部。最初のH2より前。既存の導入文がある場合は、その**前**に置く（既存導入文は削除しない）。
- 分量：**150文字以内**（句読点含む）。
- 内容：その記事の主キーワードの検索意図に対する「結論」を先に書く。何が分かる記事かではなく、問いへの答えそのものを書く。
- 形式：段落ブロック1つ。見出しにしない。太字・箇条書きにしない。
- 文体：CLAUDE.md の記事執筆ルール（禁止語・時点明記・実績捏造禁止）に従う。
- 記事の主キーワードは KWマスター（記事URL対応表）から取得する。

### 処置F：FAQブロック化
- 対象：記事内に既にある「よくある質問」相当のセクション（最後のH2の一つ手前にあるH2配下のH3群）。
- 作業：既存の質問（H3）と回答（本文）を、**内容を一文字も変えずに** Yoast SEO の FAQ ブロックへ移し替える。
- 質問文・回答文の追加・削除・言い換え・順序変更は禁止。
- 元のH2見出し（「よくある質問」等）は残す。H3は FAQ ブロックの質問に置き換わるため削除してよい。
- FAQセクションが見つからない記事があれば、**処置せず報告**する（勝手に作らない）。

## 3. 組別 対象URL

### ①対照（12本）— 触らない
- https://cross-com.jp/agentforce-data-library/
- https://cross-com.jp/agentforce-lost-deal-analysis/
- https://cross-com.jp/agentforce-coworker/
- https://cross-com.jp/salesforce-ai/
- https://cross-com.jp/agentforce-chatgpt-copilot-comparison/
- https://cross-com.jp/agentforce-pricing/
- https://cross-com.jp/agentforce-small-business/
- https://cross-com.jp/agentforce-einstein-difference/
- https://cross-com.jp/agentforce-rag/
- https://cross-com.jp/agentforce-for-sales-sdr-sales-coach/
- https://cross-com.jp/agentic-ai-guide/
- https://cross-com.jp/buyer-enablement/

### ②FAQのみ（12本）— 処置F
- https://cross-com.jp/agentforce-data-volume/
- https://cross-com.jp/agentforce-sales-dependency/
- https://cross-com.jp/agentforce-deal-notes/
- https://cross-com.jp/agentforce-employee-agent/
- https://cross-com.jp/agentforce-usecase-selection/
- https://cross-com.jp/agentforce-security-risk-design/
- https://cross-com.jp/agentforce-features/
- https://cross-com.jp/agentforce-service-agent/
- https://cross-com.jp/agentforce-roi/
- https://cross-com.jp/agentforce-retention/
- https://cross-com.jp/agentic-crm-pipeline-stagnation-detection/
- https://cross-com.jp/revops-guide/

### ③リードのみ（12本）— 処置L
- https://cross-com.jp/agentforce-no-code-scope/
- https://cross-com.jp/agentforce-sales-meeting/
- https://cross-com.jp/sfa-teichaku/
- https://cross-com.jp/agentforce-sales-roleplay/
- https://cross-com.jp/tableau-ai/
- https://cross-com.jp/agentforce-marketing/
- https://cross-com.jp/agentforce-reasoning-control/
- https://cross-com.jp/agentforce-agent-script/
- https://cross-com.jp/agentforce-certification/
- https://cross-com.jp/agentforce-testing-center/
- https://cross-com.jp/agentforce-vibes/
- https://cross-com.jp/agentforce-observability/

### ④両方（12本）— 処置L ＋ 処置F
- https://cross-com.jp/agentforce-proposal-review/
- https://cross-com.jp/agentforce-permission-set/
- https://cross-com.jp/agentforce-subagents/
- https://cross-com.jp/agentforce-voice/
- https://cross-com.jp/einstein-trust-layer/
- https://cross-com.jp/salesforce-data-360/
- https://cross-com.jp/agentforce-use-cases/
- https://cross-com.jp/agentforce-usage/
- https://cross-com.jp/agentforce-in-slack/
- https://cross-com.jp/agentforce-mcp/
- https://cross-com.jp/hyper-personalization/
- https://cross-com.jp/agentic-crm-pipeline-kpi-monitoring/

## 4. 完了報告（必須）
以下をCSVで返す：`url, group, treatment_L(0/1), treatment_F(0/1), lead_text, faq_count, applied_at(YYYY-MM-DD HH:MM), notes`
- lead_text：適用したリード文の全文
- faq_count：FAQブロックに移した質問数
- notes：FAQ不在・仕様判断に迷った点・未処置の理由

## 5. 反映後の禁止事項（観測期間 反映日〜2026-11-19）
- 48本のプール記事に対する一切の編集（実験以外）を禁止。
- 新規記事（顕在層向け）から48本への内部リンクは、張らないか、4組すべてに同じ本数で張る。
- サービスページ・著者ボックス等サイト全体に均等にかかる変更は可。
