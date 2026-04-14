# requirements.md

# DocOS / harness-llm-wiki 下一阶段优化需求文档

版本：v1.0  
日期：2026-04-14  
适用仓库：`Aidenwu0209/harness-llm-wiki`

---

## 1. 背景与判断

当前仓库已经具备了正确的系统骨架：

- 已明确四层真相：`Raw Source -> DocIR -> Knowledge -> Wiki`
- 已明确 11 步主流程：`Ingest -> Route -> Parse -> Normalize -> Extract -> Compile -> Patch -> Lint -> Harness -> Gate -> Review`
- 已明确 domain skills、patch 模式、review queue、harness gate
- 已经从“纯目录架构”进化为“有测试支撑的系统内核”

但当前阶段的核心问题也很明确：

**架构已经基本对，执行闭环还没有彻底打通。**

下一阶段的目标，不应该继续横向扩模块，而应该优先把“README 里声明的能力”完全落到“真实运行链”上。换句话说，下一步的工作重点是：

> 把 DocOS 从“架构正确的 kernel”推进到“真实可运行、可回归、可 gate、可 merge 的最小闭环系统”。

---

## 2. 当前版本的主要问题汇总

### 2.1 已发现的核心缺口

1. **CLI 主链路没有真正打通**
   - `parse` 仍直接实例化 `StdlibPDFParser`
   - `normalize` / `extract` / `compile` 仍以状态返回为主，没有真正读写完整 artifacts
   - `lint` 目前传入空的 `pages / claims / entities`
   - `eval` 尚未基于完整 artifacts 执行真实 harness gate

2. **路由配置与运行时 parser 能力尚未统一**
   - `configs/router.yaml` 中声明了 `pymupdf / pdfplumber / marker / paddleocr / tesseract`
   - 但运行主路径当前没有完全通过 `ParserRegistry + Orchestrator` 统一调度这些 parser
   - 配置声明与可执行 backend 之间还存在“文档领先实现”的现象

3. **Signal -> Router 的关键逻辑仍有偏差**
   - `_detect_dual_column()` 目前恒定返回 `False`
   - `_score_route()` 当前只把 `table_formula_heavy` 对齐到 `is_table_heavy`，没有独立使用 `is_formula_heavy`
   - `max_pages` 当前更像加分项，而不是清晰的路由边界规则

4. **Patch 仍未成为系统中心的状态转换层**
   - 新页面当前不会生成 patch，而是直接返回 `None`
   - `patch_id` 使用内建 `hash(self.body)`，不适合做重跑稳定性与可重放控制
   - `create/update/delete/apply/merge/rollback` 的 lifecycle 还没有闭环

5. **Skills 现在更像 contract 文档，而不是运行时单元**
   - `.agents/skills/*/SKILL.md` 已经写得很好
   - 但系统还没有做到“按 skills 调度”和“按 skills 做 contract tests”

6. **测试仍以组件正确性为主，缺少真实端到端金路径**
   - 目前 workflow tests 已经有价值
   - 但仍偏向“构造 DocIR 后测试后续流程”
   - 还缺一个从 raw fixture 开始、贯穿 route/parse/normalize/extract/compile/lint/eval/report 的完整 golden path

---

## 3. 本阶段总体目标

本阶段必须达成以下总目标：

### 3.1 产品级目标

系统必须至少能够稳定完成一条真实闭环：

```text
Raw Source
  -> Route
  -> Parse
  -> Normalize
  -> Extract
  -> Compile
  -> Patch
  -> Lint
  -> Harness
  -> Gate
  -> Report
```

### 3.2 工程级目标

- 所有阶段都必须落盘到统一 artifacts
- 所有 artifacts 都必须被 `run manifest` 串起来
- 所有 release decision 都必须基于真实 artifacts 和真实 gate
- 所有 patch 都必须可审计、可回放、可回滚
- 所有 route 都必须能映射到真实 parser backend
- 所有 P0 阶段都必须有 regression tests

### 3.3 本阶段不做的事

以下事项不是当前阻塞项，不能优先于 P0：

- 不优先做花哨 UI
- 不优先增加过多新 parser
- 不优先做复杂 agent orchestration
- 不优先做通用平台化抽象
- 不优先做大规模 LLM/hybrid extraction 扩张

---

## 4. 设计原则

本轮优化必须坚持以下原则：

1. **先闭环，再扩展**
2. **先真实 artifacts，再漂亮 README**
3. **先 deterministic baseline，再 hybrid intelligence**
4. **先 patch-driven state transition，再直接写 wiki**
5. **先 config/runtime 对齐，再扩 parser 数量**
6. **先 contract test，再 agent 化**

---

# 5. P0 必做需求（必须完成）

---

## P0-01：打通真实端到端金路径

### 目标
系统必须支持一条真正可执行的最小主链路，而不是“各命令分别存在但彼此没有形成真实闭环”。

### 当前问题
当前 CLI 中：

- `parse` 直接调用 `StdlibPDFParser`
- `normalize` / `extract` / `compile` 主要返回占位状态
- `lint` 没有吃到真实 wiki/knowledge 状态
- `eval` 尚未吃到完整 artifacts

### 必须实现

1. 新增一个**统一的端到端执行入口**，二选一即可：
   - `docos run <file_path>`
   - 或 `docos pipeline run <source_id>`

2. 该入口必须执行以下阶段：
   - ingest
   - route
   - parse
   - normalize
   - extract
   - compile
   - patch
   - lint
   - eval
   - report

3. 每一阶段必须：
   - 读前一阶段产物
   - 写本阶段产物
   - 更新 `RunManifest`
   - 写入 stage status / started_at / finished_at / error_detail

4. 每一阶段失败时必须：
   - 在 `RunManifest` 中写明失败阶段
   - 保存尽可能多的 debug artifact
   - 不允许静默失败

5. `report` 输出必须基于真实 run artifacts，而不是基于推测状态。

### 涉及文件

- `docos/cli/main.py`
- `docos/run_store.py`
- `docos/registry.py`
- `docos/source_store.py`
- `docos/debug_store.py`
- `docos/ir_store.py`
- `docos/knowledge_store.py`
- `docos/artifact_stores.py`
- `docos/models/run.py`

### 验收标准

- 运行一次命令后，系统能从 raw file 一直走到 report
- 所有中间产物均存在且可定位
- `report` 中能看到 route / parser / DocIR / knowledge / patch / harness / review 状态
- 任一阶段失败时，report 中能看到明确的失败阶段与错误信息

---

## P0-02：让 parse 阶段真正走 Route + Registry + Orchestrator

### 目标
`parse` 命令不能继续硬编码某个 parser；它必须遵从系统的 route 决策。

### 当前问题
当前 `parse` 直接创建 `StdlibPDFParser()`，绕过了：

- `ParserRouter`
- `ParserRegistry`
- `Orchestrator`
- fallback 机制
- route log 和 debug assets

### 必须实现

1. `parse` 阶段必须先读取已有 route decision；若不存在则先执行 route。
2. `parse` 阶段必须通过 `ParserRegistry` resolve：
   - primary parser
   - fallback parsers
3. `parse` 阶段必须由 `Orchestrator` 统一执行：
   - primary success -> 结束
   - primary fail -> fallback
   - fallback success -> 标记 fallback_used
   - 全部失败 -> run failed
4. parse 结果必须落盘：
   - parser result
   - parser metadata
   - fallback chain
   - debug assets
   - warnings / confidence / parser version

### 涉及文件

- `docos/cli/main.py`
- `docos/pipeline/parser.py`
- `docos/pipeline/orchestrator.py`
- `docos/pipeline/parsers/*`
- `docos/debug_store.py`

### 验收标准

- `parse` 不再直接 new `StdlibPDFParser`
- parse 输出中能看到 selected route 和 parser chain
- primary parser fail 时 fallback 能真实执行
- fallback 行为会记录到 manifest 和 debug asset 中

---

## P0-03：统一 router config 与 runtime parser registry

### 目标
配置里声明的 parser 必须是系统真实可执行的 parser，而不是“概念性名字”。

### 当前问题
当前 `configs/router.yaml` 中的 parser 名称，与实际运行路径中的 parser 实现未完全统一。

### 必须实现

1. 系统启动时新增**配置合法性校验**：
   - `router.yaml` 中每个 `primary_parser`
   - `router.yaml` 中每个 `fallback_parsers`
   - 都必须能被 `ParserRegistry` resolve

2. 若 parser 名称无法 resolve，系统必须：
   - 启动失败
   - 或 route 校验失败
   - 严禁静默降级

3. 两种路线只能选一种：
   - **路线 A**：缩减 `router.yaml`，只保留当前真实实现的 parser
   - **路线 B**：把 `pymupdf / pdfplumber / marker / paddleocr / tesseract` adapter 真正接入 registry

4. `pyproject.toml` 的 optional dependencies 必须与 runtime parser strategy 保持一致。

### 涉及文件

- `configs/router.yaml`
- `docos/pipeline/parser.py`
- `docos/pipeline/parsers/*`
- `docos/models/config.py`
- `pyproject.toml`

### 验收标准

- router config 中的每个 parser name 都能 resolve
- route 生成的 decision 一定可执行
- 若未安装对应 extra，错误信息清晰可见
- CI 中存在 config/runtime 一致性测试

---

## P0-04：修正 signal extractor 与 route scoring 逻辑

### 目标
让 signal 和 route scoring 变成真正可用的 deterministic routing，而不是“形式上存在”。

### 当前问题
- `_detect_dual_column()` 当前恒定返回 `False`
- `_score_route()` 仅把 `table_formula_heavy` 对齐到 `is_table_heavy`
- `is_formula_heavy` 没有真正参与路由决策
- `max_pages` 的语义不够清晰

### 必须实现

1. `_detect_dual_column()` 必须不再恒定返回 `False`。
   - 可以继续保持 heuristic
   - 也可以引入 parser-assisted detection
   - 但必须对特定 fixture 产生可验证的 `True/False`

2. `table` 与 `formula` 必须明确二选一：
   - 要么 route schema 拆成两个字段：`table_heavy` 和 `formula_heavy`
   - 要么 router 明确说明 `table_formula_heavy` 是复合信号，并同时消费 `is_table_heavy / is_formula_heavy`

3. `max_pages` 必须明确语义：
   - 是硬过滤条件
   - 还是软加分条件
   - 必须文档化，并在代码中一致实现

4. route log 必须记录真实命中的信号，至少包括：
   - file_type
   - page_count
   - needs_ocr
   - is_scanned
   - is_dual_column
   - is_table_heavy
   - is_formula_heavy
   - is_image_heavy

### 涉及文件

- `docos/pipeline/signal_extractor.py`
- `docos/pipeline/router.py`
- `configs/router.yaml`
- `tests/`

### 验收标准

- 存在至少 3 类不同 fixture，能够命中不同 route
- dual-column fixture 能让 `is_dual_column=True`
- formula-heavy fixture 能影响 route 选择
- route log 中的 matched signals 与真实输入一致

---

## P0-05：把 Patch 提升为正式状态转换层

### 目标
Patch 必须成为 wiki state 变更的唯一正式入口，而不是编译器里的附属对象。

### 当前问题
- 新页面当前不会生成 patch
- patch_id 不稳定
- 没有完整 `create/update/delete/apply/merge/rollback`
- risk / blast radius 还没有基于真实 diff 计算

### 必须实现

1. `CompiledPage.compute_patch()` 必须支持：
   - `CREATE_PAGE`
   - `UPDATE_PAGE`
   - `DELETE_PAGE`

2. 新页面必须生成 `CREATE_PAGE patch`，不得返回 `None`。

3. `patch_id` 必须改为**确定性内容哈希**，推荐：
   - `sha256(page_path + canonical_frontmatter + canonical_body + change_set)`

4. Patch 结构必须包含：
   - patch_id
   - run_id
   - source_id
   - change list
   - old/new content hash
   - risk score
   - blast radius
   - generated_at

5. 新增正式 patch lifecycle：
   - `apply_patch()`
   - `merge_patch()`
   - `rollback_patch()`
   - `reject_patch()`

6. `PatchStore` 必须保存完整 patch artifact，而不是只保存简化信息。

7. review queue 必须引用 patch，而不是抽象状态。

### 涉及文件

- `docos/wiki/compiler.py`
- `docos/models/patch.py`
- `docos/artifact_stores.py`
- `docos/review/queue.py`
- `docos/lint/checker.py`

### 验收标准

- 新页面、更新页面、删除页面都能产生 patch
- patch_id 在重复运行同一输入时保持稳定
- patch 可以被 apply/merge/rollback
- review item 能追溯到具体 patch
- `Re-ingest Diff Stability` 有真实可测基础

---

## P0-06：让 lint / harness / gate 基于真实 artifacts 运行

### 目标
`Lint -> Harness -> Gate` 必须不再是“形式存在”，而是正式的发布门禁链。

### 当前问题
- `lint` 当前没有读取真实 pages/claims/entities
- `eval` 尚未对接完整 DocIR/Knowledge/Patch/WikiState
- gate 还没有真正绑定 config 中的 release rules

### 必须实现

1. `lint` 必须读取真实 artifacts：
   - wiki pages
   - claims
   - entities
   - anchors
   - patch

2. `HarnessRunner` 必须消费真实 artifacts，而不是默认空值：
   - parse quality
   - knowledge quality
   - maintenance quality

3. `release_gates` 必须真正控制 merge / review：
   - block_on_p0_lint
   - block_on_p1_lint
   - block_on_missing_harness
   - block_on_fallback_low_confidence
   - block_on_regression_exceeded

4. `report` 必须输出清晰的 gate decision：
   - `auto_merge`
   - `review_required`
   - `blocked`

### 涉及文件

- `docos/lint/checker.py`
- `docos/harness/runner.py`
- `docos/artifact_stores.py`
- `configs/router.yaml`
- `docos/cli/main.py`

### 验收标准

- P0 lint fail 时，不能 auto-merge
- harness 缺失时，不能 auto-merge
- fallback 低置信度时，必须进入 review
- report 中能看到真实 gate reason

---

## P0-07：补齐真实端到端 regression fixtures

### 目标
必须用真实 raw fixtures 验证系统闭环，而不是只测中间对象。

### 当前问题
现有 workflow tests 已经不错，但仍偏向从构造 DocIR 开始，而不是从 raw 文档开始验证闭环。

### 必须实现

至少新增以下 fixtures：

1. **simple_text.pdf**
   - 单栏、文本主导、无需 OCR
   - 期望命中 fast route 或 fallback safe route

2. **dual_column_or_formula.pdf**
   - 双栏或公式密集
   - 期望命中 complex / table_formula route

3. **ocr_like.pdf 或 image input**
   - OCR 优先
   - 期望命中 OCR route

### 必须新增的集成测试

1. raw fixture -> route
2. raw fixture -> parse
3. raw fixture -> parse -> normalize -> extract
4. raw fixture -> full pipeline -> report
5. 同一 fixture 重跑 -> patch_id / entity_id / claim_id 稳定性检查

### 涉及文件

- `tests/test_workflow.py`
- 新增 `tests/test_e2e_pipeline.py`
- 新增 `tests/fixtures/*`

### 验收标准

- CI 中存在至少 1 条真正的 full pipeline test
- 至少 3 类 route 被 fixtures 覆盖
- 同一文档重跑时 ID 稳定性可验证
- 失败时能保留 debug artifact 便于定位

---

# 6. P1 应做需求（建议本阶段后半完成）

---

## P1-01：把 Skills 从文档契约升级为运行时单元

### 目标
让 `.agents/skills/*` 不只是说明书，而是系统的一等执行单元。

### 必须实现

1. 每个 skill 必须映射到一个真实 runtime entrypoint，例如：
   - `docos-route` -> `docos route`
   - `docos-parse` -> `docos parse`
   - `docos-extract` -> `docos extract`
   - `docos-patch` -> patch service / CLI
   - `docos-lint` -> lint profile runner
   - `docos-review` -> queue submit/resolve

2. 每个 skill 必须有 contract tests，验证：
   - Input
   - Output
   - Invariants
   - Fallback
   - Evaluation

3. skills 文档与 runtime 行为必须双向一致。

### 涉及文件

- `.agents/skills/*`
- `docos/cli/main.py`
- `tests/`

### 验收标准

- 每个 domain skill 都有对应入口
- 每个 skill 都有 contract tests
- skill 文档中声明的 invariant 在测试里能被验证

---

## P1-02：补齐 8 类页面类型的真实编译覆盖

### 目标
`PageType` 已经声明 8 类页面，必须让这些页面在编译和测试中真正闭环。

### 必须实现

至少补齐以下 page types 的 compile + test：

- `parser`
- `benchmark`

并确保以下已有页面类型继续可用：

- `source`
- `entity`
- `concept`
- `failure`
- `comparison`
- `decision`

### 涉及文件

- `docos/models/page.py`
- `docos/wiki/compiler.py`
- `tests/test_wiki_*`

### 验收标准

- 8 类页面均有 compile path
- 8 类页面均有测试
- 对应 frontmatter/body schema 稳定

---

## P1-03：增强运行可观测性与调试资产

### 目标
让每次 run 都能被定位、复盘、对比。

### 必须实现

1. `RunManifest` 中补齐：
   - selected_route
   - parser_chain
   - fallback_used
   - lint summary
   - harness summary
   - gate decision
   - review status

2. 每个 stage 记录：
   - started_at / finished_at / duration_ms
   - warnings
   - error_detail

3. Debug assets 最少包括：
   - route log
   - parser raw result
   - fallback trace
   - repair log
   - lint findings
   - harness report

### 验收标准

- 任意 run 都能从 report 追到全部核心 artifacts
- 任意失败都能快速定位到阶段和原因

---

## P1-04：文档与实现一致性治理

### 目标
避免 README 继续领先于实际实现，确保仓库对外表达与系统能力一致。

### 必须实现

1. README 中的命令、流程、page types、parser 列表必须与当前实现一致。
2. 若某功能仍为 roadmap，必须明确标注，不得写成“已经完成”。
3. 补充 `schemas/` 或 schema 导出产物：
   - `doc.schema.json`
   - `page.schema.json / yaml`
   - `patch.schema.json`

### 验收标准

- README 中的每个 CLI 命令都可运行
- README 中声明的 parser / page type / pipeline 与代码一致
- schema artifacts 可供外部审查

---

# 7. P2 后续需求（不是当前阻塞项）

---

## P2-01：引入 hybrid / LLM-assisted extraction

### 目标
在 deterministic baseline 稳定后，再提升知识抽取质量。

### 内容

- LLM-assisted entity extraction
- claim synthesis with evidence anchors
- conflict resolution suggestion
- low confidence repair suggestion

### 前提

只有在以下条件满足后才开始：

- P0 全部完成
- P1 大部分完成
- 真实 regression 已稳定

---

## P2-02：扩展 parser adapter 矩阵

### 目标
让 router 中声明的更多 parser 有正式 adapter。

### 内容

- marker adapter
- pdfplumber adapter
- OCR adapter abstraction
- parser capability metadata
- parser benchmark profile page

### 注意

扩 parser 数量之前，必须先确保 registry、orchestrator、route validation 已稳定。

---

## P2-03：Review Console / 可视化审阅台

### 目标
把 parsing wiki 从 CLI kernel 推进到真正可操作的 review UX。

### 内容

- page render view
- bbox overlay
- route diff
- parser diff
- patch diff review
- claim -> evidence drilldown

---

# 8. 文件级改造清单

## 8.1 必改文件

- `docos/cli/main.py`
- `docos/pipeline/router.py`
- `docos/pipeline/signal_extractor.py`
- `docos/pipeline/parser.py`
- `docos/pipeline/orchestrator.py`
- `docos/wiki/compiler.py`
- `docos/models/patch.py`
- `docos/harness/runner.py`
- `docos/lint/checker.py`
- `configs/router.yaml`
- `pyproject.toml`
- `tests/test_workflow.py`

## 8.2 高概率新增文件

- `tests/test_e2e_pipeline.py`
- `tests/test_router_registry_alignment.py`
- `tests/test_patch_lifecycle.py`
- `tests/test_skill_contracts.py`
- `tests/fixtures/simple_text.pdf`
- `tests/fixtures/dual_column_or_formula.pdf`
- `tests/fixtures/ocr_like.pdf`
- `docos/pipeline/runner.py` 或 `docos/workflow/run_pipeline.py`

---

# 9. 推荐实施顺序

## 阶段 1：先打穿最小闭环

1. `docos run` 统一入口
2. `parse` 改为走 route + registry + orchestrator
3. `normalize/extract/compile` 接真实 artifacts
4. `lint/eval/report` 接真实 artifacts
5. 完成 full pipeline test

## 阶段 2：再修系统正确性

1. 修 dual-column detection
2. 修 formula routing
3. 修 config/runtime alignment
4. 修 patch lifecycle
5. 修 gate/review 联动

## 阶段 3：再做产品化和技能化

1. skill runtime 化
2. page type 完整覆盖
3. schema 导出
4. README 与实现一致化

## 阶段 4：最后做能力增强

1. hybrid extraction
2. 更多 parser adapter
3. review console

---

# 10. 本阶段完成定义（Definition of Done）

只有满足以下条件，才能认为这轮优化完成：

1. 存在一条从 raw fixture 到 report 的真实可执行金路径
2. `parse` 不再绕过 router/registry/orchestrator
3. router config 与 runtime parser 完全对齐
4. dual-column / formula signals 能真实影响路由
5. patch 成为正式状态转换层，并支持 deterministic patch_id
6. lint / harness / gate 基于真实 artifacts 生效
7. 至少 1 条 full pipeline regression test 纳入 CI
8. skills 有 runtime entrypoints 和 contract tests
9. README 与实际实现一致

---

# 11. 最终一句话总结

下一阶段最重要的，不是“再加更多模块”，而是：

> **把 README 里已经声明的系统能力，全部落实为统一 artifact 驱动、run manifest 可追踪、patch/gate 真正生效的最小闭环执行链。**

只有这一步做完，`harness-llm-wiki` 才会从“方向很对的系统内核”真正进入“可持续演进的 Document Knowledge Compiler”。
