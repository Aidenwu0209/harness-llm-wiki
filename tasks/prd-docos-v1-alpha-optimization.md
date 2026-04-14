# PRD: DocOS v1 Alpha 闭环优化

## Introduction

本 PRD 基于现有 [requirement.md](/Users/wu/Desktop/wu/AAaabaidu/llm%20wiki/tasks/requirement.md) 与当前仓库快照编写，目标是把 DocOS 从“架构方向正确但闭环未成的 skeleton”推进到“可跑通最小闭环、可审计、可恢复、可回归的 v1 alpha”。

本轮优化不追求同时支持多种文档类型，也不追求先做复杂 UI。优先级只有三件事：

- 打穿单一垂直 domain 的真实闭环，建议先以 PDF 为主。
- 修复 determinism、patch/review、持久化、可回归性这些系统级问题。
- 让 README、CLI、skills、目录结构与真实实现保持一致。

## Goals

- 打通真实可执行的最小闭环：`ingest -> signal extraction -> route -> parse -> normalize -> extract -> compile -> patch -> lint -> harness -> gate -> review`
- 为 `source_id` 和 `run_id` 建立完整追溯链路，所有关键 artifacts 都必须落盘且可恢复
- 让 Wiki 更新完全经由 patch lifecycle，而不是直接写 Markdown
- 为 entity、claim、relation、anchor 建立稳定且可复现的 deterministic IDs
- 让 review queue、report、CLI 成为真实可用入口，而不是 demo 或 stub
- 增加最小端到端回归能力，确保同一文档重复 ingest 时 diff 稳定
- 沉淀与项目目标一致的 domain skills，并对齐 README/skills/repo 叙事

## User Stories

### Milestone 1: 最小闭环跑通

### US-001: 为 ingest 建立真实 run 入口
**描述：** 作为系统操作员，我想在执行 `docos ingest <file> --run` 时立即获得真实 `run_id` 和运行清单，以便后续每个阶段的产物都能被追踪和审计。

**Acceptance Criteria：**
- [ ] `docos ingest <file> --run` 返回 `source_id`、`run_id`、当前状态和 artifact 根路径
- [ ] 每次运行都会生成 run manifest，至少包含 `source_id`、`run_id`、触发时间、阶段列表、当前阶段状态
- [ ] 系统重启后仍能通过 `run_id` 找回对应 manifest
- [ ] ingest 不再只停留在 source 注册，而能进入真实 pipeline
- [ ] 相关单元测试与集成测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/cli/main.py`、`docos/registry.py`、新增 `run_store`

### US-002: 为关键 artifacts 建立正式持久化层
**描述：** 作为维护者，我想把 DocIR、knowledge、patch、report、wiki state 等对象写入正式 store，以便系统具备恢复、审计和回归能力。

**Acceptance Criteria：**
- [ ] 新增并接入 `ir_store/`、`knowledge_store/`、`patch_store/`、`run_store/`、`report_store/`、`wiki_store/`
- [ ] 任一关键对象都不只存在于内存
- [ ] `source_id` 和 `run_id` 能追溯到本次运行产生的所有 artifacts
- [ ] 系统重启后可重新查询某次运行的 DocIR、knowledge、patch、report
- [ ] 相关单元测试与集成测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** 新增 store 模块，接入 `docos/cli/main.py`、`docos/pipeline/*`、`docos/wiki/*`

### US-003: 从 raw source 中提取真实 document signals
**描述：** 作为路由器维护者，我想基于文档事实而不是默认值抽取 signals，以便 route 决策可解释、可复现且稳定。

**Acceptance Criteria：**
- [ ] 新增 `signal extraction` 模块，至少抽取 `file_type`、`extension`、`MIME`、`page_count`、`needs_ocr`、`is_scanned`、`is_dual_column`、`is_table_heavy`、`is_formula_heavy`、`is_image_heavy`、`language`、`target_mode`、`has_known_failures`
- [ ] `docos route <source_id>` 读取真实 source 和真实 signals，不再使用写死的 PDF 默认值
- [ ] route log 中保存完整 signal dump
- [ ] 同一文档在内容不变时 route 结果稳定
- [ ] 相关单元测试与集成测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/cli/main.py`、`docos/pipeline/router.py`、新增 `docos/pipeline/signals.py`

### US-004: 接入可执行的 parser registry 与 fallback orchestrator
**描述：** 作为系统操作员，我想让 route 决策能够驱动真实 parser 链，而不是抽象接口或占位逻辑，以便解析失败时还能自动 fallback。

**Acceptance Criteria：**
- [ ] `ParserRegistry` 中至少注册 1 个主 parser 和 1 个 fallback parser
- [ ] `route -> orchestrator -> parser backend` 可真实执行
- [ ] parser 主路径失败后会触发下一条 fallback route
- [ ] 每次 parser attempt 都记录 parser 名称、开始/结束时间、状态、失败原因
- [ ] parser 不可用有单独状态，而不是统一混入普通失败
- [ ] 相关单元测试与集成测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/pipeline/parser.py`、`docos/pipeline/orchestrator.py`、`pyproject.toml`

### US-005: 持久化 orchestrator attempts 与 debug assets
**描述：** 作为排障维护者，我想无论 parse 成功还是失败都保留完整 attempts 和 debug 资料，以便定位 fallback 原因和复现实验。

**Acceptance Criteria：**
- [ ] 所有 attempt 都写入 parse log，包括失败 attempt
- [ ] debug assets 不只在成功时导出，失败路径也会落盘
- [ ] `PipelineRunResult` 可持久化并关联 `source_id`、`run_id`、parser chain
- [ ] debug store 支持按 `source_id/run_id/parser` 三层浏览
- [ ] 任一次 fallback 都能查看 primary fail 的原因和 artifacts
- [ ] 相关单元测试与集成测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/pipeline/orchestrator.py`、`docos/debug_store.py`

### US-006: 让 `docos report <run_id>` 读取真实运行结果
**描述：** 作为系统操作员，我想通过 `report` 命令查看某次运行的真实产出和状态，以便判断是否需要 review 或继续排障。

**Acceptance Criteria：**
- [ ] `docos report <run_id>` 能展示 run 状态、选用 parser、产出的 artifacts 列表、lint 结果、harness 结果、review 状态
- [ ] report 内容来自真实 stores，而不是占位文本
- [ ] 对不存在的 `run_id` 返回明确错误与查询建议
- [ ] 相关单元测试与集成测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/cli/main.py`、`report_store`

### Milestone 2: 系统一致性与可追溯性

### US-007: 为 DocIR 增加完整 invariant validator
**描述：** 作为 normalizer 维护者，我想在 extract/compile 之前验证 DocIR 的系统级约束，以便非法结构被尽早阻断。

**Acceptance Criteria：**
- [ ] 覆盖 `block_id` 唯一性、page-block 引用一致性、同页 `reading_order` 唯一性、relation block 引用合法性、`page_count` 与 pages 数量一致性、`pages.blocks` 中 block 必须存在
- [ ] 任何 invariant 失败都能指出具体 `page_no` 或 `block_id`
- [ ] normalizer 输出的 DocIR 可通过全部校验
- [ ] 非法 DocIR 在进入 extract/compile 前被阻断
- [ ] 相关单元测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/models/docir.py`

### US-008: 补齐 page-local normalization 的字段映射
**描述：** 作为数据工程维护者，我想在 parser 输出转 canonical block 时保留表格、脚注、引文等信息，以便下游知识提取不会丢失关键结构。

**Acceptance Criteria：**
- [ ] `table_cells`、`footnote_refs`、`citations` 和其他 parser-specific structure fields 不会在 normalize 中被静默丢弃
- [ ] 暂不支持的字段写入 `metadata` 或 extension field
- [ ] bbox 输入长度和类型会被严格校验
- [ ] 新增 table、citation、footnote 相关 fixtures
- [ ] 相关单元测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/pipeline/normalizer.py`

### US-009: 修复 global repair 后的 page state 重建与 heading 修复
**描述：** 作为 normalizer 维护者，我想在全局修复后重建 page-level 状态，并正确保留 heading 相对层级，以便 DocIR 仍然自洽且可被下游消费。

**Acceptance Criteria：**
- [ ] global repair 后会重建 `pages.blocks`、page-level warnings、page 内 reading order、relation references
- [ ] 被移除的 block 不再残留在任何 `Page.blocks` 中
- [ ] `_normalize_heading_hierarchy()` 按 `shift` 平移 heading level，而不是把所有 heading 变成单个 `#`
- [ ] 清理不可达代码
- [ ] repair 后的 DocIR 能通过完整 invariant 校验
- [ ] 新增最小 heading level 不为 1 的测试
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/pipeline/normalizer.py`、`docos/models/docir.py`

### US-010: 为知识对象建立 deterministic IDs
**描述：** 作为知识层维护者，我想让 entity、claim、relation、anchor 在内容不变时生成稳定 ID，以便 re-ingest diff 只反映真实变化。

**Acceptance Criteria：**
- [ ] `entity_id`、`claim_id`、`relation_id`、`evidence_anchor_id` 改为确定性生成
- [ ] 生成规则使用归一化文本、`source_id`、`page_no/block_id`、语义类型等稳定输入
- [ ] 相同 source 在内容不变时重复 ingest，关键 knowledge IDs 保持稳定
- [ ] diff 不再主要受随机 UUID 漂移影响
- [ ] 相关单元测试与回归测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/knowledge/extractor.py`、`docos/knowledge/ops.py`、`docos/models/knowledge.py`

### US-011: 补齐 evidence anchors 与 section 边界提取
**描述：** 作为 reviewer，我想从 claim 直接跳回原文页面和 block，并确保 section claim 不跨 heading 污染，以便证据追溯和人工复核可执行。

**Acceptance Criteria：**
- [ ] evidence anchor 至少包含 `bbox`、char offsets、`render_uri`、quote policy 所需字段
- [ ] claim extraction 不跨越相邻 heading 污染
- [ ] 支持跨页 section、table、figure claim 的基础提取
- [ ] source summary 或 concept page 上的 evidence link 可追溯到源 block
- [ ] review 流程可消费 anchor 信息
- [ ] 相关单元测试与集成测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/models/knowledge.py`、`docos/knowledge/extractor.py`

### US-012: 修正 knowledge ops 的完整工作流
**描述：** 作为知识维护者，我想让 conflict、deprecate、dedup 成为真正会更新状态并可审批的 workflow，以便知识图谱维护具备行为正确性。

**Acceptance Criteria：**
- [ ] `mark_conflict()` 会真实更新 claim 的 `status` 与 `conflicting_sources`
- [ ] `deprecate_claim()` 在状态变化时不丢 `object_value` 或其他字段
- [ ] dedup candidate 能进入 review queue 并在审批后更新 entity graph
- [ ] 文件结构与 import 顺序清晰可维护
- [ ] 相关单元测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/knowledge/ops.py`、`docos/review/queue.py`

### US-013: 补齐 page type contract 与安全 frontmatter 生成
**描述：** 作为 wiki 维护者，我想让所有声明过的 page type 都具备内容模型和编译支持，并使用正式 YAML serializer 输出 frontmatter，以便页面生成稳定可靠。

**Acceptance Criteria：**
- [ ] `parser` 与 `benchmark` page type 拥有完整 content schema
- [ ] `PAGE_CONTENT_MAP`、page validation、compiler 对 8 种 page type 全部支持
- [ ] frontmatter 使用正式 YAML serializer，而不是手工字符串拼接
- [ ] frontmatter round-trip 测试通过，特殊字符、多语言、引号、多行文本不会破坏格式
- [ ] 相关单元测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/models/page.py`、`docos/wiki/compiler.py`

### US-014: 把 WikiCompiler 升级为 patch compiler
**描述：** 作为系统维护者，我想让 compiler 输出 `CompiledPage` 和 `Patch`，而不是直接渲染 Markdown 写文件，以便变更可审计、可评估、可回滚。

**Acceptance Criteria：**
- [ ] compiler 支持 `compile_page_state(...) -> CompiledPage`
- [ ] compiler 支持 `diff_page(existing, compiled) -> Patch`
- [ ] update 现有 page 时保留 `created_at`、page identity、existing backlinks
- [ ] compiler 可在不写文件的前提下生成完整 patch 结果
- [ ] patch 只包含最小必要变更
- [ ] 相关单元测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/wiki/compiler.py`、`docos/models/patch.py`

### US-015: 落地完整 patch lifecycle
**描述：** 作为审阅者，我想对 patch 执行生成、评估、staging、merge、rollback 的完整生命周期，以便 Wiki 更新完全受控。

**Acceptance Criteria：**
- [ ] 实现 `generate_patch`、`compute_blast_radius`、`score_patch_risk`、`apply_patch_to_staging`、`merge_patch`、`rollback_patch`
- [ ] 系统内不存在绕过 patch 直接写 Wiki 的路径
- [ ] patch 在 merge 前后有明确状态迁移
- [ ] rollback 能恢复到上一个已合并状态
- [ ] 所有页面变更都能追溯到 patch
- [ ] 相关单元测试与集成测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/models/patch.py`、`docos/wiki/compiler.py`、新增 patcher 模块

### US-016: 修复 review queue 的持久化和恢复能力
**描述：** 作为 reviewer，我想在系统重启后继续处理待审项，并查看每个 review item 的完整生命周期，以便人工审核具备可靠性。

**Acceptance Criteria：**
- [ ] ReviewQueue 初始化时会加载已有 items
- [ ] `approve`、`reject`、`request_changes` 都会落盘
- [ ] `queue`、`approved`、`rejected`、`changes_requested` 状态迁移明确
- [ ] `list_pending()` 和 `get(review_id)` 以磁盘状态为准
- [ ] 可通过 `review_id` 恢复 item 历史
- [ ] 系统重启后 review queue 不丢失
- [ ] 相关单元测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/review/queue.py`

### Milestone 3: 产品化与回归能力

### US-017: 让 lint、harness、release gate 接入真实生产流
**描述：** 作为发布守门人，我想用真实 lint findings 和 harness report 控制 patch 去向，以便坏 patch 被阻断，高风险结果进入 review。

**Acceptance Criteria：**
- [ ] lint 覆盖 frontmatter、page body、wikilink、anchor coverage、schema-body consistency
- [ ] `docir` 参数被真实消费
- [ ] release gate 由配置驱动，而不是硬编码
- [ ] harness 至少覆盖 parse、knowledge、maintenance 三类指标
- [ ] harness report 可被 release gate 直接消费
- [ ] lint findings 可阻断真实坏 patch
- [ ] 相关单元测试与集成测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/lint/checker.py`、`docos/harness/runner.py`、`docos/models/config.py`

### US-018: 把 CLI 从 demo 命令升级为真实操作入口
**描述：** 作为系统操作员，我想通过 CLI 完成 ingest、parse、compile、patch、review、report 等实际操作，以便仓库具备可用的最小产品接口。

**Acceptance Criteria：**
- [ ] `docos ingest <file> --run`、`docos parse <source_id|run_id>`、`docos compile <run_id>`、`docos patch list/apply/merge/rollback`、`docos review list/show/approve/reject/request-changes`、`docos report <run_id>` 均可输出真实状态
- [ ] CLI 中不再保留 “not yet connected” 或纯打印型 review 操作
- [ ] 参数校验和错误提示可指导用户继续排障
- [ ] 相关集成测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/cli/main.py`

### US-019: 升级 router scoring 与 parser health 机制
**描述：** 作为平台维护者，我想让 router 同时使用硬过滤、软评分和 parser health 状态，以便不同文档能稳定落到预期 route。

**Acceptance Criteria：**
- [ ] score 区分 hard filter 与 soft score
- [ ] `language`、`is_scanned`、`has_known_failures`、`target_mode`、`is_formula_heavy` 等有效 signal 参与决策
- [ ] `max_pages` 可配置为硬限制或明确的软限制
- [ ] router 接入 parser healthcheck/capability
- [ ] route 日志能输出 explainable score breakdown
- [ ] 相关单元测试通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/pipeline/router.py`、`docos/models/config.py`、`configs/router.yaml`

### US-020: 将 knowledge extraction 从 baseline 提升到可维护版本
**描述：** 作为知识工程维护者，我想把当前脆弱的 rule baseline 提升为可扩展的 hybrid pipeline，以便 extraction 质量在闭环打通后能继续演进。

**Acceptance Criteria：**
- [ ] rule-based pre-extraction 与 schema validation 明确分层
- [ ] section 边界、跨页 section、table、figure claim 的规则明确且可测试
- [ ] relation 生成 precision 明显优于 substring baseline
- [ ] LLM-assisted refinement 作为可选能力而不是默认前提
- [ ] 相关单元测试与 golden fixtures 通过
- [ ] Typecheck/lint 通过

**涉及模块：** `docos/knowledge/extractor.py`

### US-021: 对齐 README、skills 与 repo structure
**描述：** 作为新加入的开发者，我想只看 README 和 skills 就能理解系统当前能力边界与工作流，以便不会被“文档比实现走得更远”的信息误导。

**Acceptance Criteria：**
- [ ] README 只声明已实现能力和明确 roadmap，不再把未落地能力描述成现状
- [ ] 若 `schemas/` 为目标产物，则仓库中存在真实导出；否则从 README 删除
- [ ] `.agents/skills` 中新增 `route-document`、`parse-to-docir`、`normalize-structure`、`extract-entities-claims`、`generate-page-patch`、`lint-reconcile`、`review-route`、`query-wiki-grounded`
- [ ] 每个 domain skill 都定义输入 schema、输出 schema、invariants、fallback、eval
- [ ] README、CLI、目录结构、skills 的表述保持一致
- [ ] 文档检查和相关测试通过

**涉及模块：** `README.md`、`.agents/skills/`、repo 结构文档

### US-022: 建立端到端回归测试、golden fixtures 与分层依赖安装
**描述：** 作为仓库维护者，我想在 CI 中跑通最小闭环，并按能力选择依赖安装，以便系统既可回归，也可按需部署。

**Acceptance Criteria：**
- [ ] 新增 module unit tests、workflow integration tests、golden document regression tests
- [ ] 至少提供 1 个 simple PDF fixture 和 1 个 complex fixture
- [ ] CI 可跑通最小端到端流程
- [ ] re-ingest 稳定性存在明确基线指标
- [ ] `pyproject.toml` 按 `.parsers`、`.ocr`、`.llm`、`.dev` 等 optional extras 分层
- [ ] README 提供最小安装和全量安装两种方式
- [ ] 相关测试通过

**涉及模块：** `tests/`、`pyproject.toml`、`README.md`

## Functional Requirements

- FR-1: 系统必须在 ingest 时生成真实 `run_id`，并为每次运行保存可恢复的 manifest
- FR-2: 系统必须为 DocIR、knowledge、patch、report、wiki state 提供正式持久化层
- FR-3: 路由必须基于从 raw source 提取的真实 document signals 进行决策
- FR-4: 路由日志必须记录 signals、score breakdown、选中的 parser chain 和决策原因
- FR-5: 系统必须至少支持 1 条主 parser 路径与 1 条 fallback parser 路径
- FR-6: orchestrator 必须为所有 parser attempts 保存状态、失败原因和 debug assets
- FR-7: 非法 DocIR 必须在 extract/compile 前被 invariant validator 阻断
- FR-8: normalizer 不能静默丢弃表格、脚注、引文等结构化字段
- FR-9: global repair 后系统必须重建 page-level block 引用、reading order 和 relation references
- FR-10: entity、claim、relation、anchor 必须使用 deterministic IDs
- FR-11: evidence anchor 必须足以支持 review 定位、证据回跳和 quote 截取
- FR-12: knowledge ops 必须真实更新知识状态，而不是只返回 helper 对象
- FR-13: 8 种 page type 必须都有内容模型、编译支持和验证规则
- FR-14: compiler 必须输出 `CompiledPage` 和 `Patch`，而不是直接写 Wiki 文件
- FR-15: 所有 Wiki 变更都必须经过 patch lifecycle，并支持 merge 与 rollback
- FR-16: review queue 必须可持久化、可恢复、可审计
- FR-17: lint、harness、release gate 必须由真实 artifacts 与配置驱动
- FR-18: CLI 必须成为真实操作入口，不保留 demo/stub 命令
- FR-19: README、skills、目录结构必须准确反映当前系统能力边界
- FR-20: 系统必须具备最小端到端回归测试和 golden fixtures
- FR-21: 依赖安装必须支持按 parser/OCR/LLM/dev 能力分层

## Non-Goals

- 本轮不以多 MIME type 平台化为目标，优先只打透 PDF domain
- 本轮不实现完整 review/evidence 可视化控制台
- 本轮不追求自动 merge 覆盖所有场景，高风险 patch 仍以 review 为主
- 本轮不以“提高 LLM 生成质量”作为第一优先级，先保证闭环、一致性和可回归
- 本轮不先扩展大量 parser 数量，优先做 1 条主路径加 1 条可靠 fallback
- 本轮不把 Markdown 提升为唯一机器真相，DocIR 仍是机器层主真相

## Design Considerations

- 先以单一 PDF domain 建立最小闭环，再扩展其他格式
- 用户可感知的主流程必须是 patch-driven，而不是 direct write
- review queue、report、CLI 需要面向排障与审计设计，不只是“成功路径”
- stories 应按三段实施：
  - Milestone 1：跑通闭环
  - Milestone 2：修一致性与可追溯
  - Milestone 3：补产品化与回归能力
- domain skills 与 workflow 要分离：
  - `skills/` 负责能力 contract
  - `workflow/` 负责阶段编排

## Technical Considerations

- 当前仓库已有清晰模块边界：`cli`、`pipeline`、`knowledge`、`wiki`、`lint`、`harness`、`review`
- 当前主要问题不是缺模块，而是 stub、持久化缺失、随机 ID、patch lifecycle 未落地、文档漂移
- parser 接入应优先选择易落地的 PDF 路径，例如 text-heavy 主 parser 加 lightweight fallback
- deterministic ID 设计必须优先考虑 re-ingest stability，避免把随机性带入 diff 和 review
- patch lifecycle 与 review queue 需要共享状态模型，避免出现“patch 已变更但 queue 不可恢复”的情况
- lint、harness、release gate 必须共享统一配置来源，避免规则散落在硬编码里
- golden fixtures 需要覆盖 simple 和 complex 两类 PDF，不能只测 happy path

## Success Metrics

- 单一 PDF 文档可跑通完整闭环，且 `docos ingest <file> --run` 产生真实 `run_id`
- 任一 `run_id` 都能追溯到 source、DocIR、knowledge、patch、lint、harness、review artifacts
- 所有 Wiki 更新都经过 patch lifecycle，不存在绕过 patch 的直接写路径
- 相同 source 在内容不变时重复 ingest，核心 knowledge IDs 稳定
- `docos report <run_id>` 能展示真实运行结果，而不是占位文本
- review queue 可在系统重启后恢复，且 lifecycle 可审计
- README 不再宣称未实现能力，domain skills 与系统目标一致
- 至少 1 个 simple fixture 与 1 个 complex fixture 可跑通最小回归
- `Re-ingest Diff Stability` 达到可衡量基线，并朝 README 目标值持续收敛

## Open Questions

- 首个主 parser 与 fallback parser 的具体技术选型是什么，是否优先 `pymupdf` + `pdfplumber`
- `wiki_store` 的页面落盘格式是否继续沿用现有 Markdown 路径，还是先增加 staging 区
- `render_uri` 与 review 引用高亮的最小实现是什么，是否先用 page/block drilldown 代替复杂渲染层
- LLM-assisted refinement 是否在 alpha 阶段保持默认关闭，只通过 feature flag 启用
- domain skills 的目录位置是继续沿用 `.agents/skills/`，还是需要补充 workflow 专用目录
