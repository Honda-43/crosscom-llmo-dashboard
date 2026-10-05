# 47本の本文の変化（2026-10-05）

実験期間中は47本の本文を変えない。ここに記事が出ているということは、
把握していない経路で本文が変わったということ。**原因を確かめるまで、
その記事の引用率の増減を処置の効果として読まないこと。**

- 比べた基準：処置後の基準（2026-09-30 取得。9/29〜30 の処置による変化は想定内として除いた）
- 本文テキストが変化した記事（想定外）：**0 本 / 46 本**
- HTMLのみの変化（本文テキストは同一・要確認）：32 本
- 取得できなかった記事：0 本

## HTMLのみの変化（本文テキストは同一）

表示される文字は同じで、HTML（属性・リンク先・マークアップ）だけが違う。
9/18→9/21→9/30 に47本すべてが ±7 バイト往復した例がある（原因は未特定・テキストは同一）。
リンク先や属性の変化もここに入るため、本数が多い週は1本を開いて確かめる。

| slug | 基準 | 今回 |
|---|---|---|
| agentforce-observability | 2026-09-30 `caadb1266733` | `f2d6caaf81c7` |
| agentforce-roi | 2026-09-30 `0176a224d068` | `a663669c37bc` |
| agentforce-rag | 2026-09-30 `4aca293b5a4d` | `c76ae4d634ce` |
| agentforce-einstein-difference | 2026-09-30 `1c7e964d096d` | `da5af134dbe2` |
| agentforce-mcp | 2026-09-30 `cf1ff2f24c85` | `2ede6a210685` |
| agentforce-features | 2026-09-30 `b739f5799a09` | `b448fc36aced` |
| agentforce-testing-center | 2026-09-30 `63023ef79a70` | `73c81380b4a1` |
| agentforce-certification | 2026-09-30 `5b98fff0235a` | `a9b7e3ffbad2` |
| agentforce-chatgpt-copilot-comparison | 2026-09-30 `55e93a95aa1b` | `55ab97460242` |
| agentforce-security-risk-design | 2026-09-30 `c12e17efcf64` | `dea414e95742` |
| agentforce-usage | 2026-09-30 `84fb4ef6b879` | `63533baefe2e` |
| agentforce-use-cases | 2026-09-30 `7485d16c22b8` | `12972963316e` |
| agentforce-agent-script | 2026-09-30 `dd2846582288` | `84ad39bfdc77` |
| agentforce-reasoning-control | 2026-09-30 `48bc30bcaae9` | `933a500ceb07` |
| buyer-enablement | 2026-09-30 `2a8373874750` | `f1e159d5b991` |
| salesforce-ai | 2026-09-30 `c43b28357256` | `0fcb282eaa58` |
| agentforce-marketing | 2026-09-30 `b4e9890cfc57` | `7e08d9bef2ce` |
| salesforce-data-360 | 2026-09-30 `654aa973c550` | `5e43c9f8c7fc` |
| hyper-personalization | 2026-09-30 `a37d17faec3e` | `4a032e2d4e2e` |
| revops-guide | 2026-09-30 `a00d73e3ff8c` | `9fe55f870fc1` |
| agentic-ai-guide | 2026-09-30 `3d0ce5ef773f` | `65385011c801` |
| einstein-trust-layer | 2026-09-30 `b7f4d436071c` | `bb122852b735` |
| agentforce-employee-agent | 2026-09-30 `713b8352d522` | `9ac227e06b09` |
| tableau-ai | 2026-09-30 `8746816d8ee0` | `c4e62716fc42` |
| agentforce-voice | 2026-09-30 `c667f6295cd6` | `3ff904bf4a93` |
| agentforce-subagents | 2026-09-30 `e53031608e73` | `85b5e4342f26` |
| sfa-teichaku | 2026-09-30 `af193b942cfe` | `47ffa6098177` |
| agentforce-sales-dependency | 2026-09-30 `14fae104fe7e` | `eda42cb31a55` |
| agentforce-no-code-scope | 2026-09-30 `5f4fc762bcf1` | `47b98907d66d` |
| agentforce-data-volume | 2026-09-30 `4d33dc18a6a3` | `2675787dfe26` |
| agentforce-data-library | 2026-09-30 `67c345b67e69` | `9fea1f56b677` |
| agentforce-permission-set | 2026-09-30 `ed988530bc62` | `822be44fc018` |

### agentforce-observability：HTML の違う箇所

```
insert: …top-challenge-for-sales-objectives-in-two-thousand-twenty-si">こちら</a></p><h3 id="arkb-toc-5" class="wp-block-heading">原因… → …top-challenge-for-sales-objectives-in-two-thousand-twenty-si" target="_blank" rel="noopener noreferrer">こちら</a></p><h3 id="arkb-toc-5" class="wp-block-heading">原因…
insert: …stories/agentforce-studio-observability-tools-announcement/">こちら</a></p><h3 id="arkb-toc-44" class="wp-block-heading">層③… → …stories/agentforce-studio-observability-tools-announcement/" target="_blank" rel="noopener noreferrer">こちら</a></p><h3 id="arkb-toc-44" class="wp-block-heading">層③…
insert: …nt-analytics-and-monitoring/monitor-agent-metrics-and-scores">こちら</a></p><h3 id="arkb-toc-49" class="wp-block-heading">観… → …nt-analytics-and-monitoring/monitor-agent-metrics-and-scores" target="_blank" rel="noopener noreferrer">こちら</a></p><h3 id="arkb-toc-49" class="wp-block-heading">観…
insert: …om/s/articleView?id=005316995&amp;language=en_US&amp;type=1">こちら</a></p><h3 id="arkb-toc-56" class="wp-block-heading">変更… → …om/s/articleView?id=005316995&amp;language=en_US&amp;type=1" target="_blank" rel="noopener noreferrer">こちら</a></p><h3 id="arkb-toc-56" class="wp-block-heading">変更…
insert: …com/s/articleView?id=005305353&amp;language=en_US&amp;type=1">こちら</a></p><h3 id="arkb-toc-57" class="wp-block-heading">変… → …com/s/articleView?id=005305353&amp;language=en_US&amp;type=1" target="_blank" rel="noopener noreferrer">こちら</a></p><h3 id="arkb-toc-57" class="wp-block-heading">変…
insert: …les.sales_agent_sdr_intro.htm&amp;language=en_US&amp;type=5">こちら</a></p><h3 id="arkb-toc-61" class="wp-block-heading">前提… → …les.sales_agent_sdr_intro.htm&amp;language=en_US&amp;type=5" target="_blank" rel="noopener noreferrer">こちら</a></p><h3 id="arkb-toc-61" class="wp-block-heading">前提…
```

### agentforce-roi：HTML の違う箇所

```
insert: …op-challenge-for-sales-objectives-in-two-thousand-twenty-si">こちら</a></p><p class="wp-block-paragraph">※参考記事は<a href="htt… → …op-challenge-for-sales-objectives-in-two-thousand-twenty-si" target="_blank" rel="noopener noreferrer">こちら</a></p><p class="wp-block-paragraph">※参考記事は<a href="htt…
insert: …top-challenge-for-sales-objectives-in-two-thousand-twenty-si">こちら</a></p><p class="wp-block-paragraph"><mark style="back… → …top-challenge-for-sales-objectives-in-two-thousand-twenty-si" target="_blank" rel="noopener noreferrer">こちら</a></p><p class="wp-block-paragraph"><mark style="back…
insert: …t-analytics-and-monitoring/monitor-agent-metrics-and-scores">こちら</a></p><p class="wp-block-paragraph">この産業用部材メーカーの実証では、こ… → …t-analytics-and-monitoring/monitor-agent-metrics-and-scores" target="_blank" rel="noopener noreferrer">こちら</a></p><p class="wp-block-paragraph">この産業用部材メーカーの実証では、こ…
insert: …com/s/articleView?id=005135173&amp;language=en_US&amp;type=1">こちら</a></p><h3 id="arkb-toc-45" class="wp-block-heading">機… → …com/s/articleView?id=005135173&amp;language=en_US&amp;type=1" target="_blank" rel="noopener noreferrer">こちら</a></p><h3 id="arkb-toc-45" class="wp-block-heading">機…
insert: …com/s/articleView?id=005237036&amp;language=en_US&amp;type=1">こちら</a></p><p class="wp-block-paragraph">この産業用部材メーカーでは、実証を… → …com/s/articleView?id=005237036&amp;language=en_US&amp;type=1" target="_blank" rel="noopener noreferrer">こちら</a></p><p class="wp-block-paragraph">この産業用部材メーカーでは、実証を…
insert: …cent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027">こちら</a></p><p class="wp-block-paragraph">※参考記事は<a href="htt… → …cent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027" target="_blank" rel="noopener noreferrer">こちら</a></p><p class="wp-block-paragraph">※参考記事は<a href="htt…
```

### agentforce-rag：HTML の違う箇所

```
insert: ….com/s/articleView?id=ai.data_library_parent.htm&amp;type=5">こちら</a></p><h3 id="arkb-toc-2" class="wp-block-heading">Age… → ….com/s/articleView?id=ai.data_library_parent.htm&amp;type=5" target="_blank" rel="noopener noreferrer">こちら</a></p><h3 id="arkb-toc-2" class="wp-block-heading">Age…
insert: ….com/s/articleView?id=ai.data_library_parent.htm&amp;type=5">こちら</a></p><h3 id="arkb-toc-21" class="wp-block-heading">Ti… → ….com/s/articleView?id=ai.data_library_parent.htm&amp;type=5" target="_blank" rel="noopener noreferrer">こちら</a></p><h3 id="arkb-toc-21" class="wp-block-heading">Ti…
insert: …-cloud-powered-agentforce/explore-data-cloud-and-agentforce">こちら</a></p><div class="schema-faq wp-block-yoast-faq-block"… → …-cloud-powered-agentforce/explore-data-cloud-and-agentforce" target="_blank" rel="noopener noreferrer">こちら</a></p><div class="schema-faq wp-block-yoast-faq-block"…
```
