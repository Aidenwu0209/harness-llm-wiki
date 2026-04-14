# PRD: Document Parsing Knowledge OS Optimization

## 1. Introduction

本 PRD 基于 `tasks/requirements.md`，将当前项目的优化目标拆分为可执行的产品需求与实施阶段。

目标不是继续堆叠零散功能，而是把项目优化为一套专业级、证据优先、可审阅、可回归、可维护的 Document Parsing Knowledge OS。

系统目标链路如下：

```text
Raw Sources -> Parser Router -> Canonical DocIR -> Claim/Entity Graph -> Markdown Wiki -> Review & Harness
```

本 PRD 只做需求拆分，不涉及代码修改。

## 2. Goals

- 建立从原始文档到知识页面的清晰分层，避免过早扁平化为 Markdown。
- 让关键 claim、entity、concept 都能追溯到原始证据锚点。
- 让 parser、schema、patch、review、harness 成为可版本化、可回归、可审计的流程。
- 支持增量更新与重复 ingest，而不是每次全量重写知识库。
- 为高风险变更建立 review gate，为质量建立 harness gate。
- 先打通 PDF-only MVP，再逐步扩展到多格式与平台化能力。

## 3. Scope

### In Scope

- PDF 文档 ingest 优化
- Source Registry 与重复导入管理
- Parser Router 与 primary/fallback parser 机制
- Canonical DocIR 定义、归一化、结构修复与版本化
- Claim / Entity / Relation 抽取
- Markdown Wiki 编译与增量更新
- Patch / lint / review / merge 流程
- Harness / regression / release gate
- Failure mode 沉淀与 parser compare
- Review Console 与 Markdown/Obsidian 协作工作区

### Out of Scope

- 纯无人值守全自动发布
- 面向公众的 SaaS 计费系统
- 通用搜索引擎替代
- 持续网页爬虫
- 全格式一次性覆盖
- 高级 agent swarm 编排

## 4. Phase Breakdown

### Phase 0: Specification First

目标：先冻结真相层、结构层、规则层，避免后续返工。

交付：

- `DocIR Schema`
- `Patch Schema`
- `Page Schema / Template`
- `Skills Contract`
- `Thresholds / Review Policy`

### Phase 1: PDF-only MVP

目标：打通最小闭环。

交付：

- PDF ingest
- Router + parser
- Canonical DocIR
- Source / Entity / Concept 页面
- 基础 lint / report

### Phase 2: Quality Gates

目标：让结果从“能跑”变成“可验证”。

交付：

- Golden Set v1
- Harness v1
- Regression report
- Release gates

### Phase 3: Review and Risk Control

目标：让复杂解析与高风险 patch 进入人工可控流程。

交付：

- Review queue
- Review Console
- Parser compare
- High-risk patch policy

### Phase 4: Knowledge Operations

目标：支持长期维护。

交付：

- Conflict management
- Entity dedup workflow
- Failure library
- Incremental knowledge updates

### Phase 5: Platformization

目标：扩展为稳定平台能力。

交付：

- Batch ingest
- 多环境配置
- 更完整的 CLI / API
- 多格式支持

## 5. User Stories

### US-001: 建立 Source Registry
**描述：** 作为系统，我需要为每个导入文档分配稳定的 `source_id`，以便支持重复导入、版本追踪和知识页关联。

**Acceptance Criteria：**
- [ ] 每个 source 具备稳定且唯一的 `source_id`
- [ ] 系统通过 hash 识别重复文档
- [ ] 系统记录 ingest 历史、最新 run、最新 DocIR
- [ ] source 与 wiki page 支持双向索引

### US-002: 解析前进行 Router 选择
**描述：** 作为系统，我需要在解析前选择合适的 route，以便在复杂度、成本与保真之间做可解释的平衡。

**Acceptance Criteria：**
- [ ] Router 输入至少包含文件类型、页数、是否扫描件、是否表格/公式密集等信号
- [ ] Router 输出包含 `selected_route`、`primary_parser`、`fallback_parsers`
- [ ] 路由原因被显式记录
- [ ] 路由策略可配置而非写死在 prompt 中

### US-003: 支持 primary / fallback parser
**描述：** 作为系统，我需要在 primary parser 失败时自动降级，以便单个 parser 异常不导致整个 ingest 流程失效。

**Acceptance Criteria：**
- [ ] 至少支持一个 primary parser 和一个 fallback parser
- [ ] primary parser 失败时自动记录失败原因并触发 fallback
- [ ] fallback 使用结果需要进入更严格 review policy
- [ ] 系统保留 parser compare 所需的差异数据

### US-004: 统一输出 Canonical DocIR
**描述：** 作为系统，我需要把不同 parser 的输出归一化为 Canonical DocIR，以便后续知识抽取和 wiki 编译基于统一真相层工作。

**Acceptance Criteria：**
- [ ] DocIR 包含 page、block、relation 三层结构
- [ ] 保留 reading order、bbox、跨页 continuity relation
- [ ] unknown block 不得被静默丢弃
- [ ] DocIR 可通过 schema 校验

### US-005: 记录结构修复与归一化过程
**描述：** 作为工程师，我需要看到每次 repair 的 before/after 和原因，以便调试归一化逻辑并保证可审计。

**Acceptance Criteria：**
- [ ] 每次 repair 记录 `repair_id`、`repair_type`、`before`、`after`
- [ ] repair 记录包含 `reason`、`confidence`、`performed_by`
- [ ] 原 parser 输出被保留，不被覆盖
- [ ] 修复记录可关联到最终 DocIR

### US-006: 抽取结构化 Entity / Claim / Relation
**描述：** 作为知识工程师，我需要系统从 DocIR 中抽取结构化知识对象，以便后续知识维护不是自由文本总结。

**Acceptance Criteria：**
- [ ] 系统可抽取 entity、claim、relation
- [ ] `supported` claim 必须具备 evidence anchor
- [ ] `inferred` claim 必须具备推理说明
- [ ] conflict claim 被显式标记

### US-007: 生成 Source Page
**描述：** 作为最终使用者，我需要每份文档都有 source page，以便从文档维度查看摘要、结构、证据与后续知识映射。

**Acceptance Criteria：**
- [ ] 每个 source 自动生成对应 source page
- [ ] source page 具备 frontmatter、基础元数据和结构导航
- [ ] source page 可跳转到 evidence link
- [ ] source page 可追踪关联 claims / entities / concepts

### US-008: 更新 Entity / Concept 页面
**描述：** 作为最终使用者，我需要 entity / concept 页面随新 source 增量更新，以便知识库持续演化而不是被重写。

**Acceptance Criteria：**
- [ ] 支持 entity / concept 页面新增与更新
- [ ] 页面更新遵循 patch 模式
- [ ] 不得隐式合并冲突实体
- [ ] 页面保留 frontmatter、source_docs、related_claims 等核心字段

### US-009: 通过 Patch 更新 Wiki
**描述：** 作为系统，我需要通过 patch 而不是直接写入 wiki，以便控制风险、支持审阅和回滚。

**Acceptance Criteria：**
- [ ] 系统输出结构化 patch
- [ ] patch 记录变更页面、影响 claim 数、影响链接数
- [ ] patch 可标记 `review_required`
- [ ] patch 支持后续 approve / reject / rollback

### US-010: 计算 Risk Score 与 Blast Radius
**描述：** 作为审阅者，我需要系统在 merge 前给出 patch 风险评估，以便高风险变更不会静默进入正式知识库。

**Acceptance Criteria：**
- [ ] 每个 patch 都有 risk score
- [ ] 每个 patch 都有 blast radius 统计
- [ ] 高 blast radius patch 自动进入 review queue
- [ ] 风险分级结果可解释

### US-011: 运行 Lint
**描述：** 作为系统，我需要在 merge 前执行结构与知识层 lint，以便发现 schema、链接、证据与实体层问题。

**Acceptance Criteria：**
- [ ] 能识别 schema violation、broken link、orphan page
- [ ] 能识别 unsupported claim、duplicate entity candidates
- [ ] lint 结果区分 P0/P1/P2/P3
- [ ] P0 / P1 问题阻止 auto merge

### US-012: 运行 Harness 并输出发布建议
**描述：** 作为产品负责人，我需要每次 ingest 都生成 harness report 和 release decision，以便系统具备稳定的质量门禁。

**Acceptance Criteria：**
- [ ] 每次 ingest 都运行 harness
- [ ] harness 覆盖 parse quality、knowledge quality、maintenance quality
- [ ] 系统生成结构化 harness report 与 regression summary
- [ ] 未通过 release gates 的结果不得 auto merge

### US-013: 沉淀 Failure Mode
**描述：** 作为团队，我需要把解析失败场景沉淀为 failure page，以便已知问题可以被积累、复用和对比。

**Acceptance Criteria：**
- [ ] 失败场景可生成 failure page 或 failure report
- [ ] failure page 可关联 source、route、parser、问题类型
- [ ] 典型失败模式可被分类与检索
- [ ] failure page 支持后续更新

### US-014: 提供 Review Queue
**描述：** 作为审阅者，我需要一个 review queue 来集中处理高风险 patch、复杂表格、复杂公式和冲突 claim。

**Acceptance Criteria：**
- [ ] 高风险 patch 自动进入 review queue
- [ ] queue 可显示 patch 摘要、风险、目标对象
- [ ] 支持 approve / reject / request changes
- [ ] 审阅操作带 reviewer、时间、原因日志

### US-015: 提供 Review Console
**描述：** 作为审阅者，我需要在 Review Console 中查看原页、bbox、reading order 和 claim-evidence drilldown，以便真正审阅复杂解析结果。

**Acceptance Criteria：**
- [ ] 支持原始页面查看
- [ ] 支持 bbox overlay 与 reading order overlay
- [ ] 支持 claim -> evidence drilldown
- [ ] 支持 patch diff 与 parser A/B compare

### US-016: 支持增量知识维护
**描述：** 作为系统，我需要在新 source 到来时做增量更新与冲突管理，以便长期维护知识库而非反复重写。

**Acceptance Criteria：**
- [ ] 新 source 触发相关页面增量更新
- [ ] 冲突 claim 被标记并保留双方证据
- [ ] 旧结论不得被静默覆盖
- [ ] 支持 deprecated 标记与替代指向

## 6. Functional Requirements

- FR-1: 系统必须支持 PDF 文档导入。
- FR-2: 系统必须为每个 source 分配稳定唯一的 `source_id`。
- FR-3: 系统必须通过 hash 检测重复导入。
- FR-4: 系统必须保留原始文档不可变副本。
- FR-5: 系统必须记录 source ingest 历史。
- FR-6: 系统必须在解析前执行 route 选择。
- FR-7: 系统必须支持 primary parser 与 fallback parser。
- FR-8: 系统必须记录 route 原因、parser 版本与 debug 资产。
- FR-9: 系统必须生成 Canonical DocIR。
- FR-10: DocIR 必须保存 page、block、relation、bbox、reading order。
- FR-11: DocIR 必须通过 schema 校验。
- FR-12: 系统不得静默丢弃 unknown block。
- FR-13: 系统必须记录 normalization / repair 过程。
- FR-14: 系统必须抽取 entity、claim、relation。
- FR-15: `supported` claim 必须绑定 evidence anchor。
- FR-16: `inferred` claim 必须带推理说明。
- FR-17: 冲突 claim 必须显式标记。
- FR-18: 系统必须生成 source page。
- FR-19: 系统必须支持 entity / concept 页面增量更新。
- FR-20: 所有 wiki 页面必须具备 frontmatter。
- FR-21: 系统必须通过 patch 更新 wiki。
- FR-22: 系统必须为 patch 计算 risk score 与 blast radius。
- FR-23: 系统必须运行结构层与知识层 lint。
- FR-24: 高风险 patch 必须进入 review queue。
- FR-25: 系统必须支持 approve / reject / rollback。
- FR-26: 系统必须对每次 ingest 运行 harness。
- FR-27: 系统必须生成 ingest report 与 regression report。
- FR-28: 未通过 release gate 的结果不得 auto merge。
- FR-29: 系统必须支持 failure page / failure report。
- FR-30: 系统必须提供 Review Console。
- FR-31: Review Console 必须支持 claim-evidence drilldown。
- FR-32: 系统必须支持 parser compare。
- FR-33: 系统必须支持冲突管理、实体候选去重和 deprecated 策略。

## 7. Non-Goals

- 不在本阶段实现全格式完整覆盖
- 不在本阶段实现公众产品化 SaaS 能力
- 不在本阶段实现复杂企业 IAM 集成
- 不采用一个 super prompt 直接统治全流程
- 不允许 LLM 直接覆盖正式 wiki 结果
- 不以 Markdown 作为唯一机器真相层

## 8. Design Considerations

- Markdown / Obsidian 继续作为人类浏览与协作主界面
- source、entity、concept、failure、comparison、decision 页面需要统一模板
- 证据与结论应尽量邻近展示，减少人工核对成本
- Review Console 需要围绕“原页 + overlay + claim drilldown”设计，而不是只做文本 diff

## 9. Technical Considerations

- 原始文档、DocIR、Knowledge Graph、Wiki 需要保持清晰分层
- 所有关键配置必须外置，包括 route、threshold、review policy、page template
- 系统默认采用 `generate patch -> lint -> review -> merge`
- harness 需要支持 parse、knowledge、maintenance 三类指标
- schema、parser、config 都必须版本化
- 重复 ingest 结果应尽量稳定且可复现

## 10. Success Metrics

- citation coverage >= 95%
- unsupported claim rate <= 2%
- broken wikilink count = 0
- schema violation count = 0
- re-ingest diff stability >= 90%
- duplicate entity rate <= 3%
- stale anchor rate <= 2%
- 单份中等复杂度 PDF 可在可接受时间内生成首个可用 source page

## 11. Open Questions

- Phase 1 的 parser backend 具体选择哪两个实现？
- v1 的 Review Console 是做最小可用版还是一次到位支持完整 overlay 能力？
- entity dedup 在 v1 中是只做候选提示，还是包含人工合并流程？
- failure page 与 parser compare 页面在信息架构上是否单独作为一级 page type？
- release gate 的阈值是否按 route / parser 分层设置？

## 12. Recommended Execution Order

1. 冻结 `DocIR Schema`
2. 冻结 `Patch Schema` 与 page template
3. 冻结 skills contract 与 review policy
4. 打通 `PDF -> Router -> Parser -> DocIR -> Source Page`
5. 接入 entity / claim / relation 抽取
6. 接入 patch / lint / harness
7. 接入 review queue
8. 最后建设 Review Console、failure library、platformization
