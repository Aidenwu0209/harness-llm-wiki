# harness-llm-wiki 优化 requirement.md

版本：2026-04-14  
适用范围：基于当前 `main` 分支仓库快照的优化清单  
文档目的：把当前仓库从“架构方向正确但闭环未成的 skeleton”推进到“可跑通最小闭环、可审计、可回归的 v1 alpha”

---

## 1. 执行摘要

当前仓库**方向是对的**：你已经把系统设计成 `Raw Source → Router → DocIR → Knowledge → Wiki → Review/Harness`，也明确把 `DocIR` 定义成机器真相，把 Markdown 降为视图层。

但当前仓库的主要问题不是“模块太少”，而是下面四件事还没有闭环：

1. **端到端流程没有真正跑通**：CLI 里 `parse / normalize / extract / compile / lint / eval / review / report` 大量还是 stub。  
2. **持久化层不完整**：Raw/Registry 有了，但 `DocIR / knowledge / patch / run report / merge state` 还没有正式存储层。  
3. **系统一致性与可回归性不足**：随机 ID、repair 后 page-block 引用不一致、review queue 不可恢复、patch lifecycle 没落地。  
4. **README / skills / repo 结构和真实实现存在漂移**：文档讲的是系统级产品，但代码里很多关键链路还停留在 contract 或 placeholder。

这份 requirement 的核心目标不是继续“加更多模块”，而是：

- 先打穿 **一条最小可运行闭环**
- 再修复 **determinism / patch / review / harness** 这四个系统级根问题
- 最后再把它整理成真正可复用的 **LLM Wiki Skills + Workflow**

---

## 2. 当前阶段判断

### 2.1 正确的部分

- 系统分层是正确的：Raw、DocIR、Knowledge、Wiki 没有混为一谈。
- Patch-first 思路是正确的：没有直接把 LLM 输出写进 wiki。
- Router / Normalizer / Review / Harness / Lint 已经有了模块边界。
- 这已经是一个 **system skeleton**，不是 prompt demo。

### 2.2 当前真实定位

当前仓库更准确的定位是：

> **Document Knowledge Compiler / DocOS 的 v0 系统内核**

而不是：

- 已经可用的完整产品
- 已经成型的一套 domain-specific skills
- 已经打通的 document parsing wiki pipeline

---

## 3. 优化总目标

本轮优化后，系统必须达到下面的最小目标：

1. 对单一垂直 domain（建议先 PDF 文档）跑通完整 ingest 闭环。  
2. 从 raw source 产出可落盘的 DocIR、knowledge objects、patch、review item、harness report。  
3. 所有知识对象具备**稳定 ID**与**可追溯 evidence anchor**。  
4. wiki 更新必须经由 `patch → lint → harness → gate → review/merge`。  
5. 至少有一组 domain-specific skills，而不是只有通用 skill 目录。  
6. README、代码、目录结构、CLI 行为保持一致。

---

## 4. 本轮优化的总原则

1. **先闭环，再扩展 parser 数量**。  
2. **先修一致性，再优化生成质量**。  
3. **先 deterministic，再谈 re-ingest stability**。  
4. **先 patch-driven，再做自动 merge**。  
5. **先一个 domain 打透，再做通用平台化**。

---

## 5. P0 requirements（必须先完成）

## REQ-P0-001：打通最小可运行闭环

### 当前问题
- `docos/cli/main.py` 中，`parse / normalize / extract / compile / lint / eval / review / report` 仍然是 stub 或静态输出。
- 当前 `ingest` 只做 raw 存储与 source 注册，没有触发真正的 pipeline。

### 要求
实现一条真正可执行的最小闭环：

`ingest -> signal extraction -> route -> parse -> normalize -> extract -> compile -> patch -> lint -> harness -> gate -> review`

### 验收标准
- 执行一次 ingest 后，系统至少能落盘以下 artifacts：
  - source record
  - pipeline run manifest
  - DocIR
  - entities / claims / relations
  - patch
  - lint findings
  - harness report
  - review item（如需要）
- `docos report <run_id>` 可以读取真实运行结果，不再输出占位文本。

### 影响文件
- `docos/cli/main.py`
- `docos/pipeline/*`
- `docos/wiki/*`
- `docos/lint/*`
- `docos/harness/*`
- `docos/review/*`

---

## REQ-P0-002：引入真实的运行状态与持久化层

### 当前问题
当前有 RawStorage、SourceRegistry、DebugAssetStore，但缺少正式的：
- DocIR store
- knowledge store
- patch store
- run store
- harness report store
- merged wiki state store

### 要求
新增以下持久化层：

- `ir_store/`：保存 `DocIR`
- `knowledge_store/`：保存 entities / claims / relations
- `patch_store/`：保存待审/已审/已合并 patch
- `run_store/`：保存每次 ingest 的 run manifest
- `report_store/`：保存 lint / harness / review report
- `wiki_store/`：保存当前 wiki 文件与 page metadata

### 验收标准
- 任一 run 可在系统重启后完整恢复查询。
- `source_id` 和 `run_id` 可追溯到对应的所有 artifacts。
- 没有任何关键对象只存在于内存。

---

## REQ-P0-003：实现真实的文档信号提取，而不是伪路由

### 当前问题
`route` CLI 当前使用的是：
- 一个几乎空的 `SourceRecord`
- 一个固定写死的 `DocumentSignals(file_type="application/pdf")`

这意味着当前路由不是“基于文档事实”，而是“基于默认值”。

### 要求
新增 `signal extraction` 模块，从 raw source 中提取：
- file type / extension / MIME
- page_count
- scanned / OCR need
- dual-column
- table-heavy
- formula-heavy
- image-heavy
- language
- target mode
- known failure hints

### 验收标准
- `docos route <source_id>` 读取真实 source 和真实信号。
- 路由决策日志中包含完整 signal dump。
- 同一文档在无内容变化时，route 结果稳定。

### 影响文件
- `docos/cli/main.py:41-63`
- `docos/pipeline/router.py`
- 新增 `docos/pipeline/signals.py`

---

## REQ-P0-004：落地 concrete parser adapters 与 parser registry wiring

### 当前问题
当前 `ParserBackend` / `ParserRegistry` 只有抽象层，没有 concrete parser adapter；`pyproject.toml` 也没有 parser / OCR / LLM provider 相关依赖。

### 要求
至少接入一条真实 parser 路径：
- 1 个主 parser
- 1 个 fallback parser
- 统一输出到 canonical DocIR

建议先做：
- `pymupdf` / `pdfplumber` 这种 text-heavy route
- 或者 1 个 complex parser + 1 个 lightweight fallback

### 验收标准
- `ParserRegistry` 中可枚举实际 parser。
- `route -> orchestrator -> parser backend` 可真实执行。
- parser 失败后可 fallback 到下一条 route。

### 影响文件
- `docos/pipeline/parser.py`
- `docos/pipeline/orchestrator.py`
- `pyproject.toml`

---

## REQ-P0-005：Patch 必须从概念升级为真实执行对象

### 当前问题
虽然 `Patch` model 已定义，但 `WikiCompiler` 目前返回的是 `(frontmatter, markdown_body, page_path)` tuple，不是正式 patch；当前没有 `patch apply / merge / rollback` 执行层。

### 要求
实现完整 patch lifecycle：

- `generate_patch(existing_page, compiled_page)`
- `compute_blast_radius(patch)`
- `score_patch_risk(patch)`
- `apply_patch_to_staging(patch)`
- `merge_patch(patch)`
- `rollback_patch(patch_id)`

### 验收标准
- 系统内**没有直接写 wiki 的路径**。
- 所有页面变更都能追溯到 patch。
- patch 在 merge 前后有明确状态迁移。
- rollback 可恢复到上一个已合并状态。

### 影响文件
- `docos/models/patch.py`
- `docos/wiki/compiler.py`
- 新增 `docos/wiki/patcher.py` 或 `docos/patches/*`

---

## REQ-P0-006：引入 deterministic IDs，修复 re-ingest 不稳定

### 当前问题
`knowledge/extractor.py` 里 `_make_id()` 使用随机 UUID，为 entity / claim / relation / anchor 生成随机 ID。这样会导致：
- 同一文档重复 ingest，ID 全变
- diff stability 失效
- patch blast radius 虚高
- dedup / merge / review 很难做

### 要求
将下列对象改为**确定性 ID**：
- entity_id
- claim_id
- relation_id
- evidence_anchor_id
- review_id（至少可追踪）

建议采用：
- 内容归一化文本
- source_id
- page_no / block_id
- 语义类型
- 哈希派生

### 验收标准
- 同一 source 在内容不变的情况下 re-ingest，关键 knowledge ID 稳定。
- diff 主要反映真实内容变化，而不是随机 ID 漂移。
- README 中的 `Re-ingest Diff Stability >= 90%` 变得可实现。

### 影响文件
- `docos/knowledge/extractor.py:59-60`
- `docos/knowledge/ops.py`
- `docos/models/knowledge.py`

---

## REQ-P0-007：补齐 DocIR 真正的 invariants 校验

### 当前问题
`DocIR` 的 docstring 写明了多条 invariant，但当前只实现了 `block_id` 唯一性校验，没有覆盖：
- page-block 引用一致性
- 同页 reading_order 唯一性
- relation block 引用合法性
- page_count 与 pages 数量一致性
- pages.blocks 中 block_id 必须存在

### 要求
为 `DocIR` 增加系统级 validator，覆盖以上约束。

### 验收标准
- 非法 DocIR 在进入 extract/compile 前被阻断。
- 每条报错能指出 page_no/block_id。
- normalizer 输出的 DocIR 可通过全部校验。

### 影响文件
- `docos/models/docir.py`

---

## REQ-P0-008：修复 page-local normalization 的字段丢失问题

### 当前问题
`PageLocalNormalizer._convert_block()` 当前没有把以下字段正确搬运到 canonical Block：
- `table_cells`
- `footnote_refs`
- `citations`
- 其他 parser-specific structure fields 的扩展映射

这会导致从 parser 输出到 DocIR 的信息丢失。

### 要求
- 补齐 canonical block 的字段映射。
- 对于暂不支持的 parser-specific 字段，要保留在 `metadata` 或 extension field 中，而不是默默丢弃。
- 对 bbox 输入长度和类型做更严格校验。

### 验收标准
- 复杂表格 / 引文 / 脚注相关字段不会在 normalize 过程中消失。
- 新增 fixture 覆盖 table / citation / footnote block。

### 影响文件
- `docos/pipeline/normalizer.py:117-155`

---

## REQ-P0-009：修复 global repair 后 page-block 引用不一致

### 当前问题
`GlobalRepair.repair()` 修改了 `blocks`，但返回 `DocIR` 时直接复用了 `pages=docir.pages`。如果 repair 删除 header/footer 或重组 block，`pages.blocks` 会与真实 block 集合失配。

### 要求
在所有 global repair 结束后，重新构建：
- `pages.blocks`
- page-level warnings
- reading order
- relation references

### 验收标准
- repair 前后 `DocIR` 仍能通过完整 invariant 校验。
- 被移除的 block 不再出现在任何 `Page.blocks` 中。
- 新增/重排 block 后 page 内顺序一致。

### 影响文件
- `docos/pipeline/normalizer.py:173-204`

---

## REQ-P0-010：修复 heading repair 的实质性 bug

### 当前问题
`_normalize_heading_hierarchy()` 当前逻辑会把所有 heading 统一改成单个 `#`，而不是按照 `shift` 做层级平移。并且末尾有不可达的 `return blocks`。

### 要求
- 正确按 `shift` 调整 heading level。
- 保留原层级差异。
- 清理不可达代码。

### 验收标准
- 输入 `###` / `####`，在 shift 后仍保留相对层级差。
- normalizer 测试覆盖最小 level 不为 1 的场景。

### 影响文件
- `docos/pipeline/normalizer.py:234-260`

---

## REQ-P0-011：修复 ReviewQueue 的持久化与恢复问题

### 当前问题
当前 `ReviewQueue`：
- 初始化时不会从磁盘加载已有 item
- `request_changes` 不会持久化
- `approve/reject` 会写到新目录，但原 queue 中旧文件不处理
- `list_pending()` 只看内存，不看磁盘

### 要求
- 启动时加载已有 review items。
- 所有 action 都要落盘。
- 明确 queue / approved / rejected / changes_requested 的状态迁移。
- 支持通过 review_id 恢复 item 历史。

### 验收标准
- 系统重启后 review queue 不丢失。
- `request_changes` 也可恢复。
- 一个 review item 的全生命周期可审计。

### 影响文件
- `docos/review/queue.py:111-155`

---

## REQ-P0-012：补齐 page type contract，当前 8 类只落了 6 类

### 当前问题
`PageType` 中声明了 8 种 page type：
- source
- entity
- concept
- parser
- benchmark
- failure
- comparison
- decision

但 `PAGE_CONTENT_MAP` 只覆盖了 6 类，缺少：
- parser
- benchmark

### 要求
- 为 `parser` 和 `benchmark` 增加 content schema。
- 让编译器和 page validation 真正完整支持这 8 类。

### 验收标准
- 8 种 page type 均有内容模型、编译方法、lint 规则。
- 不再存在“enum 已声明但 content model 未定义”的半闭环状态。

### 影响文件
- `docos/models/page.py:21-31`
- `docos/models/page.py:168-176`
- `docos/wiki/compiler.py`

---

## REQ-P0-013：让 WikiCompiler 真正成为 patch compiler，而不是 markdown renderer

### 当前问题
当前 `WikiCompiler` 主要是 Markdown 字符串拼接器：
- 没有读取 existing page
- 没有 diff
- 没有 risk / blast 计算
- 没有 patch 产出
- 每次 compile 都重置 `created_at`

### 要求
将 compiler 升级为：
- `compile_page_state(...) -> CompiledPage`
- `diff_page(existing, compiled) -> Patch`
- `render_page(...)`

并保留 `created_at`、page identity、existing backlinks。

### 验收标准
- 对已有 page 的 update 不会重置 `created_at`。
- patch 只包含最小必要变更。
- compiler 可以在“不写文件”的前提下生成完整 patch 结果。

### 影响文件
- `docos/wiki/compiler.py:74-79`
- `docos/wiki/compiler.py:96-108`

---

## REQ-P0-014：替换手写 frontmatter 序列化，避免 YAML 脆弱性

### 当前问题
当前 `_frontmatter_yaml()` 手工拼 YAML，存在潜在问题：
- Python list repr 与严格 YAML 不完全等价
- 特殊字符 / 多行 title / 字段转义脆弱
- 字段顺序与空值策略不可控

### 要求
使用正式 YAML serializer 生成 frontmatter，并为 frontmatter 做 round-trip test。

### 验收标准
- 生成的 frontmatter 可稳定被 YAML parser 读回。
- 特殊字符、引号、多语言文本不会破坏格式。

### 影响文件
- `docos/wiki/compiler.py:40-58`

---

## REQ-P0-015：让 lint / harness / release gate 真正接入生产流

### 当前问题
- `lint` 目前只收 `Frontmatter`，无法检查页面正文、wikilink、anchor 一致性。
- `docir` 参数未使用。
- `ReleaseGate` 没有真正消费 `AppConfig.release_gates` / `lint_policy`。
- `HarnessRunner` 的指标过于轻量，且 `unsupported_claim_rate` 基本是 model validation 的重复约束。

### 要求
- lint 扩展到 page body / link graph / anchor coverage / schema-body consistency。
- release gate 改成 config-driven。
- harness 至少覆盖 parse / knowledge / maintenance 三类真实指标。

### 验收标准
- lint findings 能阻断真实坏 patch。
- gate 的阻断条件由 config 控制，而不是硬编码。
- harness report 可被 release gate 直接消费。

### 影响文件
- `docos/lint/checker.py`
- `docos/harness/runner.py`
- `docos/models/config.py`

---

## 6. P1 requirements（重要但可在闭环后完成）

## REQ-P1-001：升级 router scoring 逻辑，避免误路由

### 当前问题
当前 router 评分存在几个明显缺口：
- `is_formula_heavy` 没真正参与评分
- `max_pages` 只是加分项，不是硬限制
- `language / is_scanned / has_known_failures / target_mode` 未参与决策
- 未结合 parser health / capabilities
- tie-break 只靠 route 顺序

### 要求
升级 route scoring：
- 区分 hard filter 与 soft score
- 使用全部有效 signal
- 接入 parser healthcheck
- 输出 explainable score breakdown

### 验收标准
- 不同文档类型能稳定落到预期 route。
- route log 能解释每一项得分/扣分。

### 影响文件
- `docos/pipeline/router.py:176-204`
- `docos/models/config.py`
- `configs/router.yaml`

---

## REQ-P1-002：补齐 orchestrator 的运行语义与 debug 完整性

### 当前问题
当前 orchestrator 存在这些问题：
- 没有 parse 前 healthcheck
- 只在成功时导出 debug assets，失败 attempt 没有完整调试信息
- 没有持久化 `PipelineRunResult`
- 没有 timeout / retry / parser unavailable 的细分状态

### 要求
- 所有 attempt（包括失败）都写 parse log。
- parser 不可用要有单独状态和告警。
- run result 必须落盘，并关联 source_id / run_id / parser chain。

### 验收标准
- 任一次 fallback 都能查看 primary fail 的原因与 artifacts。
- debug store 能按 source/run/parser 三层浏览。

### 影响文件
- `docos/pipeline/orchestrator.py`
- `docos/debug_store.py`

---

## REQ-P1-003：升级 knowledge extraction，从规则 baseline 进化为 hybrid pipeline

### 当前问题
当前 extractor 只是 baseline：
- heading -> concept entity
- heading section -> structural claim
- 字符串包含 -> relation

问题包括：
- 只看同页 paragraph，跨页 section 会丢失
- 不会在下一个 heading 截断 section
- relation 规则过于脆弱
- evidence anchor 过于简陋

### 要求
设计 hybrid extraction：
- rule-based pre-extraction
- LLM-assisted refinement（可选）
- schema validation
- conflict-aware claim generation

### 验收标准
- claim extraction 不再跨越相邻 heading 污染。
- 支持跨页 section / table / figure claim。
- relation 生成 precision 显著高于 substring baseline。

### 影响文件
- `docos/knowledge/extractor.py`

---

## REQ-P1-004：补齐 evidence anchor 的完整字段与可视化对接

### 当前问题
当前 anchor 只填了少量字段，缺少：
- bbox
- char offsets
- render_uri
- canonical quote policy

### 要求
anchor 必须能支撑：
- 追溯回原文 block
- review UI 高亮定位
- 证据 diff
- 页面内 quote 截取

### 验收标准
- review UI 能从 claim 直接跳回源页面和 block。
- source summary / concept page 中的 evidence link 可点击追溯。

### 影响文件
- `docos/models/knowledge.py`
- `docos/knowledge/extractor.py`

---

## REQ-P1-005：修正 knowledge ops 的行为正确性

### 当前问题
- `mark_conflict()` 只返回 `ConflictMarker`，并不更新 claim 的 status / conflicting_sources。
- `deprecate_claim()` 重建 ClaimRecord 时丢失了 `object_value` 字段。
- `DedupCandidate` 与 review queue 没有真正联通。
- 文件末尾的 `Literal` import 放在底部，风格和可维护性较差。

### 要求
- conflict、deprecate、dedup 都必须是完整 workflow，而不是孤立 helper。
- deprecate/merge 时不得丢字段。
- dedup 候选进入 review queue 后可落地审批。

### 验收标准
- 被标记冲突的 claim 在知识层状态真实更新。
- deprecate 前后 claim 内容除状态变化外不丢字段。
- entity dedup 审批后能真正更新 entity graph。

### 影响文件
- `docos/knowledge/ops.py`

---

## REQ-P1-006：CLI 需要从演示命令升级为真正的操作入口

### 当前问题
CLI 现在更像 demo：
- `ingest` 只注册 source
- `route` 只返回静态决策
- `review approve/reject` 只打印文本
- `report` 只打印 not found

### 要求
将 CLI 升级为真实入口：
- `docos ingest <file> --run`
- `docos parse <source_id|run_id>`
- `docos compile <run_id>`
- `docos patch list/apply/merge/rollback`
- `docos review list/show/approve/reject/request-changes`
- `docos report <run_id>`

### 验收标准
- CLI 的所有命令都有真实状态输出。
- 不再保留“not yet connected”类命令。

---

## REQ-P1-007：把 skills 做成 domain skills，而不是 generic skills

### 当前问题
当前 `.agents/skills/` 目录主要还是通用 skill（如 browser / prd / ralph），并没有真正把 document parsing wiki 的核心能力沉淀成 skill contract。

### 要求
新增以下 domain skills：
- `route-document`
- `parse-to-docir`
- `normalize-structure`
- `extract-entities-claims`
- `generate-page-patch`
- `lint-reconcile`
- `review-route`
- `query-wiki-grounded`

同时把 workflow 与 skill 分离：
- `skills/` 只定义 contract
- `workflow/` 负责编排

### 验收标准
- 任一 skill 都有：输入 schema、输出 schema、invariants、fallback、eval。
- `.agents/skills` 与 repo 的真实系统目标一致。

---

## REQ-P1-008：修复 README / repo / skills 三者之间的漂移

### 当前问题
当前存在多处“文档比实现走得更远”的情况：
- README 描述的是完整系统，但 CLI 和 patch lifecycle 尚未打通。
- README 提到 `schemas/`，当前仓库根目录可见结构里未体现该目录。
- README 以“8 page types”表述，但当前 content model 与 compiler 尚未完整闭环。

### 要求
- README 只能声明当前已实现能力与明确 roadmap。
- `schemas/` 若为目标产物，则必须落盘导出；否则从 README 删除。
- skills、CLI、目录结构、设计文档必须保持一致。

### 验收标准
- 新人只看 README，就能正确理解系统当前能力边界。
- 文档与实现不再相互误导。

---

## REQ-P1-009：补充 end-to-end 测试与 golden fixtures

### 当前问题
当前 tests 以模块级单元测试为主，缺少覆盖：
- 实际 ingest 闭环
- re-ingest stability
- patch lifecycle
- fallback route
- review / merge / rollback
- golden doc fixtures

### 要求
增加三类测试：
- module unit tests
- workflow integration tests
- golden document regression tests

### 验收标准
- 至少有 1 个 simple PDF fixture + 1 个 complex fixture。
- CI 能跑通最小端到端流程。
- re-ingest 稳定性有明确基线指标。

---

## REQ-P1-010：依赖管理改成 extras 分层

### 当前问题
`pyproject.toml` 当前只有基础依赖，不适合真实 parser / OCR / LLM integration。

### 要求
按能力拆 optional extras，例如：
- `[project.optional-dependencies].parsers`
- `.ocr`
- `.llm`
- `.dev`

### 验收标准
- 用户可按 route 需求安装依赖，而不是一次性装满。
- README 提供最小安装与全量安装两种方式。

---

## 7. P2 requirements（闭环后再做）

## REQ-P2-001：导出真实 schema artifacts

### 要求
从 Pydantic 模型导出：
- `schemas/doc.schema.json`
- `schemas/knowledge.schema.json`
- `schemas/page.schema.json`
- `schemas/patch.schema.json`

### 验收标准
- 仓库中存在可供外部工具直接消费的 schema 文件。
- schema version 变更有 migration 说明。

---

## REQ-P2-002：建设 review / evidence 可视化界面

### 要求
在 Obsidian 之外补一个 review console，支持：
- 原始页面渲染
- bbox overlay
- claim → evidence drilldown
- parser A/B diff
- patch diff review

### 验收标准
- reviewer 不需要直接读 JSON 才能做判断。

---

## REQ-P2-003：支持多 domain / 多 MIME type 扩展

### 要求
在 PDF 打透后，再扩展到：
- image docs
- docx
- slides
- mixed corpora

### 验收标准
- 不在当前 P0/P1 阶段强行做成通用平台。

---

## 8. 关键代码问题清单（按文件归档）

## 8.1 `docos/cli/main.py`
- `route` 读取的是伪 `SourceRecord` 和写死的 PDF signal。
- `parse / normalize / extract / compile / lint / eval / report` 都未接入真实状态。
- `review approve/reject` 只是打印，不会修改 ReviewQueue。

## 8.2 `docos/pipeline/router.py`
- score 未使用全部 signal。
- `max_pages` 语义过弱。
- route 没有接 parser health / capability。

## 8.3 `docos/pipeline/orchestrator.py`
- 只对成功解析导出 debug assets。
- 没有 attempt 级 health / timeout / persistence。

## 8.4 `docos/pipeline/normalizer.py`
- `_convert_block()` 丢字段。  
- global repair 后 `Page.blocks` 不重建。  
- heading shift 有 bug。  
- caption relation 修复不更新 block-level target。  
- cross-page continuation 规则过粗糙。

## 8.5 `docos/models/docir.py`
- 文档声明的 invariant 未完全实现。  
- 缺少 page/block/relation cross-validation。

## 8.6 `docos/models/page.py`
- `PageType` 有 8 种，但 `PAGE_CONTENT_MAP` 只有 6 种。  
- 缺少 parser/benchmark content contract。

## 8.7 `docos/wiki/compiler.py`
- 实质是 Markdown renderer，不是 patch compiler。  
- frontmatter 用手工 YAML。  
- update 会重置 `created_at`。  
- 未生成 patch / diff / blast / risk。

## 8.8 `docos/knowledge/extractor.py`
- 随机 ID 破坏 determinism。  
- section claim 抽取范围不准确。  
- relation 逻辑过于脆弱。  
- anchor 信息不完整。

## 8.9 `docos/knowledge/ops.py`
- `mark_conflict()` 没更新 claim。  
- `deprecate_claim()` 会丢 `object_value`。  
- dedup 与 review queue 未打通。  
- 底部 `Literal` import 需要清理。

## 8.10 `docos/review/queue.py`
- 初始化不 reload。  
- `request_changes` 不落盘。  
- queue/approved/rejected 生命周期不清楚。

## 8.11 `docos/lint/checker.py`
- lint 对 page body / wikilink / anchor coverage 无感知。  
- `ReleaseGate` 没真正配置化。  
- `docir` 参数未消费。

## 8.12 `docos/harness/runner.py`
- parse quality 过于粗糙。  
- maintenance quality 太窄。  
- unsupported metric 与 model validation 高度重叠。  
- regression 检查太轻。

## 8.13 `pyproject.toml`
- 缺少 parser / OCR / LLM provider extras。  
- 当前依赖不足以支撑 README 描述的真实功能。

## 8.14 repo structure / `.agents/skills`
- README 所描述的系统能力与当前 skill 目录不一致。  
- 缺少 document parsing wiki 的 domain skills。

---

## 9. 推荐实施顺序

### 阶段 1：打穿闭环（必须优先）
1. REQ-P0-001 最小闭环
2. REQ-P0-002 持久化层
3. REQ-P0-003 真实 signal extraction
4. REQ-P0-004 concrete parser adapters
5. REQ-P0-005 patch lifecycle

### 阶段 2：修系统一致性
6. REQ-P0-006 deterministic IDs
7. REQ-P0-007 DocIR invariants
8. REQ-P0-008 / 009 / 010 normalizer 修复
9. REQ-P0-011 review queue durability
10. REQ-P0-012 / 013 / 014 page/compiler closure
11. REQ-P0-015 lint/harness/gate 真接入

### 阶段 3：做成可维护产品
12. REQ-P1-001 ~ REQ-P1-010
13. 再开始做 parser 扩展、review UI、多 domain

---

## 10. 本轮优化完成的 Definition of Done

当且仅当满足以下条件，本轮优化才算完成：

1. `docos ingest <file>` 能产生真实 `run_id`。  
2. 可以从 run_id 追到 source、DocIR、knowledge、patch、lint、harness、review。  
3. wiki 页面变更全部经过 patch。  
4. 同一文档重复 ingest，核心 knowledge IDs 稳定。  
5. review queue 可重启恢复。  
6. README 不再宣称未实现能力。  
7. `.agents/skills` 中存在真正的 domain-specific LLM wiki skills。  
8. 至少有 1 组 golden fixtures 跑通完整回归。

---

## 11. 一句话结论

当前仓库**不是方向错了**，而是典型的：

> **架构已经到位，但系统闭环、状态持久化、determinism、patch/review/harness 还没有落地。**

所以优化重点不该再是“多加模块”，而应当是：

> **把一条最小闭环打通，并让它可审计、可恢复、可回归。**

