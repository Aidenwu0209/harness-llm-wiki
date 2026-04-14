# PRD: DocOS 下一阶段闭环优化

## Introduction

本 PRD 基于 [requirement.md](/Users/wu/Desktop/wu/AAaabaidu/llm%20wiki/tasks/requirement.md) 与当前仓库快照编写，目标是把 DocOS 从“架构已经成型但执行闭环未彻底打通的 kernel”推进到“真实可运行、可回归、可 gate、可 merge 的最小闭环系统”。

当前仓库的问题不是缺模块，而是以下能力仍未完全落地：

- CLI 主链路还没有真正形成统一闭环。
- parser route、registry、orchestrator 之间还没有完全对齐。
- signal extraction 与 route scoring 仍有伪逻辑或弱逻辑。
- patch 还没有成为 wiki state 变更的正式状态转换层。
- lint、harness、gate 还没有完整基于真实 artifacts 生效。
- skills、README、schema 声明与真实运行行为仍有漂移。

本轮优化不以扩更多 parser、做 UI、做复杂 agent orchestration 为优先级，而是优先把 README 已声明的系统能力落实到真实执行链。

## Goals

- 打通一条从 raw fixture 到 report 的真实端到端金路径
- 让 `parse` 阶段完全遵循 `Route + ParserRegistry + Orchestrator`，不再绕过系统设计
- 让每个阶段都写入真实 artifacts，并由 `RunManifest` 串联
- 让 patch 成为 wiki 变更的唯一正式入口，并具备确定性 `patch_id`
- 让 lint、harness、gate 基于真实 artifacts 决策 `auto_merge`、`review_required`、`blocked`
- 增加可回归的真实 fixtures 和 full pipeline regression tests
- 让 domain skills、README、schema artifacts 与当前实现保持一致

## User Stories

### Milestone 1: 打通最小闭环

### US-001: 新增统一的 pipeline 执行入口
**描述：** 作为系统操作员，我想通过一个统一命令执行完整 pipeline，以便 DocOS 不再依赖分散且不连通的 CLI 命令。

**Acceptance Criteria：**
- [ ] 新增 `docos run <file_path>` 或 `docos pipeline run <source_id>` 之一作为统一入口
- [ ] 该入口按顺序执行 ingest、route、parse、normalize、extract、compile、patch、lint、eval、report
- [ ] 统一入口在任一阶段失败时都会终止后续阶段并返回失败阶段信息
- [ ] 相关单元测试与集成测试通过
- [ ] Typecheck/lint 通过

### US-002: 为每次运行保存完整 RunManifest
**描述：** 作为维护者，我想把每次运行的阶段状态和 artifacts 写入 `RunManifest`，以便后续 report、review 和排障都能回溯。

**Acceptance Criteria：**
- [ ] 每次运行都会创建一个真实 `run_id`
- [ ] `RunManifest` 至少记录 `source_id`、阶段列表、`started_at`、`finished_at`、`status`、`error_detail`
- [ ] 每个阶段都会更新自己的状态到 `RunManifest`
- [ ] 系统重启后能重新读取已有 `RunManifest`
- [ ] 相关单元测试与集成测试通过
- [ ] Typecheck/lint 通过

### US-003: 让各阶段产物落盘到统一 artifacts stores
**描述：** 作为维护者，我想让 route、parse、DocIR、knowledge、patch、lint、harness、report 等产物都真实落盘，以便系统是 artifact-driven 而不是内存驱动。

**Acceptance Criteria：**
- [ ] route、parser result、DocIR、knowledge、patch、lint findings、harness report 都有正式落盘路径
- [ ] `RunManifest` 能关联每个 artifact 的定位信息
- [ ] 失败阶段也会尽可能保留 debug artifacts
- [ ] 没有关键阶段结果只存在于内存
- [ ] 相关单元测试与集成测试通过
- [ ] Typecheck/lint 通过

### US-004: 让 `report` 基于真实 run artifacts 输出结果
**描述：** 作为系统操作员，我想通过 `docos report <run_id>` 查看真实运行结果，以便判断 pipeline 是否可继续、是否需要 review。

**Acceptance Criteria：**
- [ ] `report` 基于真实 run artifacts 输出，而不是基于推测或占位状态
- [ ] `report` 中能看到 route、parser、DocIR、knowledge、patch、harness、review 状态
- [ ] 失败 run 的 `report` 中能显示失败阶段和错误原因
- [ ] 相关单元测试与集成测试通过
- [ ] Typecheck/lint 通过

### Milestone 2: 修正 route / parse / signal 主链

### US-005: 让 `parse` 阶段走真实 Route + Registry + Orchestrator
**描述：** 作为平台维护者，我想让 `parse` 完全遵守系统路由与 fallback 设计，以便 parser 执行链真实可复现。

**Acceptance Criteria：**
- [ ] `parse` 不再直接实例化单个 parser
- [ ] `parse` 会先读取已有 route decision；若不存在则先执行 route
- [ ] `parse` 通过 `ParserRegistry` resolve `primary_parser` 和 `fallback_parsers`
- [ ] `parse` 由 `Orchestrator` 统一执行 primary / fallback
- [ ] 相关单元测试与集成测试通过
- [ ] Typecheck/lint 通过

### US-006: 为 parser fallback 保存真实链路与 metadata
**描述：** 作为排障维护者，我想看到 parser chain、fallback 使用情况和 parser metadata，以便 route/parse 失效时能快速定位问题。

**Acceptance Criteria：**
- [ ] parse 输出中包含 selected route、primary parser、fallback chain、最终使用 parser
- [ ] primary parser 失败时 fallback 会真实执行
- [ ] parser result 会保存 warnings、confidence、parser version 和 debug assets
- [ ] fallback 行为会写入 `RunManifest` 和 debug artifacts
- [ ] 相关单元测试与集成测试通过
- [ ] Typecheck/lint 通过

### US-007: 校验 router config 与 runtime parser registry 一致
**描述：** 作为平台维护者，我想确保 `router.yaml` 中声明的 parser 都能被 registry resolve，以便配置不是概念模型而是可执行配置。

**Acceptance Criteria：**
- [ ] 系统启动或 route 校验时会验证 `primary_parser` 和 `fallback_parsers` 都能被 resolve
- [ ] 无法 resolve 的 parser name 会导致明确失败，而不是静默降级
- [ ] `pyproject.toml` 的 optional dependencies 与 runtime parser strategy 保持一致
- [ ] CI 中存在 config/runtime 一致性测试
- [ ] 相关单元测试通过
- [ ] Typecheck/lint 通过

### US-008: 修正 signal extractor 的 dual-column 检测
**描述：** 作为路由维护者，我想让 dual-column 检测产生真实信号，以便双栏文档能命中正确 route。

**Acceptance Criteria：**
- [ ] `_detect_dual_column()` 不再恒定返回 `False`
- [ ] 至少一个 dual-column fixture 会得到 `is_dual_column=True`
- [ ] dual-column 检测结果会进入 route log
- [ ] 相关单元测试通过
- [ ] Typecheck/lint 通过

### US-009: 修正 formula/table/max_pages 的 route scoring 语义
**描述：** 作为路由维护者，我想让 formula-heavy、table-heavy 和 `max_pages` 的语义清晰且一致，以便 route 决策可解释、可预测。

**Acceptance Criteria：**
- [ ] `is_formula_heavy` 会真实参与 route 选择
- [ ] table 与 formula 的 schema/评分逻辑是明确的，不再是隐含映射
- [ ] `max_pages` 被明确实现为硬过滤或软加分之一，并在代码与配置中保持一致
- [ ] route log 中至少记录 `file_type`、`page_count`、`needs_ocr`、`is_scanned`、`is_dual_column`、`is_table_heavy`、`is_formula_heavy`、`is_image_heavy`
- [ ] 至少 3 类 fixture 能命中不同 route
- [ ] Typecheck/lint 通过

### Milestone 3: 让 patch 成为正式状态转换层

### US-010: 为 create/update/delete 三类页面生成正式 patch
**描述：** 作为 wiki 维护者，我想让页面创建、更新、删除都生成正式 patch，以便 wiki state 变更统一受控。

**Acceptance Criteria：**
- [ ] `CompiledPage.compute_patch()` 支持 `CREATE_PAGE`、`UPDATE_PAGE`、`DELETE_PAGE`
- [ ] 新页面生成 `CREATE_PAGE patch`，不再返回 `None`
- [ ] patch artifact 中包含 change list、old/new content hash、`run_id`、`source_id`
- [ ] 相关单元测试通过
- [ ] Typecheck/lint 通过

### US-011: 为 patch 引入确定性 `patch_id`
**描述：** 作为系统维护者，我想让同一输入重复运行时得到稳定的 `patch_id`，以便 diff stability 和重放控制具备基础。

**Acceptance Criteria：**
- [ ] `patch_id` 改为基于 canonical 内容的确定性哈希
- [ ] 同一输入重复运行时 `patch_id` 稳定
- [ ] `patch_id` 不再依赖 Python 内建 `hash()`
- [ ] 相关单元测试与稳定性测试通过
- [ ] Typecheck/lint 通过

### US-012: 落地 patch lifecycle 与 review 引用关系
**描述：** 作为 reviewer，我想对 patch 执行 apply、merge、rollback、reject，并从 review item 追溯到具体 patch，以便审阅流程可执行、可回滚。

**Acceptance Criteria：**
- [ ] 实现 `apply_patch()`、`merge_patch()`、`rollback_patch()`、`reject_patch()`
- [ ] `PatchStore` 保存完整 patch artifact，而不是简化信息
- [ ] review queue 引用具体 `patch_id`
- [ ] patch 变更状态在 lifecycle 中可追踪
- [ ] 相关单元测试与集成测试通过
- [ ] Typecheck/lint 通过

### Milestone 4: 让 lint / harness / gate 成为真实门禁

### US-013: 让 `lint` 读取真实 wiki / knowledge / patch artifacts
**描述：** 作为发布守门人，我想让 lint 针对真实产物运行，以便坏 patch 不会被误判为通过。

**Acceptance Criteria：**
- [ ] `lint` 读取真实 wiki pages、claims、entities、anchors、patch
- [ ] lint 不再使用默认空对象或占位输入
- [ ] P0 lint fail 时，系统不能 auto-merge
- [ ] 相关单元测试与集成测试通过
- [ ] Typecheck/lint 通过

### US-014: 让 `HarnessRunner` 与 release gates 消费真实 artifacts
**描述：** 作为发布守门人，我想让 harness 和 gate 基于真实 DocIR、Knowledge、Patch、WikiState 决策，以便 release decision 有真实依据。

**Acceptance Criteria：**
- [ ] `HarnessRunner` 消费真实 parse/knowledge/maintenance artifacts
- [ ] `release_gates` 能真实控制 `auto_merge`、`review_required`、`blocked`
- [ ] harness 缺失时不能 auto-merge
- [ ] fallback 低置信度时必须进入 review
- [ ] `report` 中能输出真实 gate reason
- [ ] Typecheck/lint 通过

### Milestone 5: 建立真实 regression 基线

### US-015: 增加 raw fixtures 覆盖 simple / complex / OCR 三类输入
**描述：** 作为测试维护者，我想用真实 raw fixtures 覆盖主要 route 类型，以便验证 route 和 parse 逻辑不是只在构造对象上成立。

**Acceptance Criteria：**
- [ ] 新增 `simple_text.pdf`
- [ ] 新增 `dual_column_or_formula.pdf`
- [ ] 新增 `ocr_like.pdf` 或等效 image input fixture
- [ ] 每类 fixture 都有预期 route
- [ ] 相关测试通过
- [ ] Typecheck/lint 通过

### US-016: 新增 full pipeline integration tests
**描述：** 作为测试维护者，我想从 raw fixture 开始跑完整 pipeline，以便验证系统存在真实金路径，而不是只测中间层。

**Acceptance Criteria：**
- [ ] 覆盖 raw fixture -> route
- [ ] 覆盖 raw fixture -> parse
- [ ] 覆盖 raw fixture -> parse -> normalize -> extract
- [ ] 覆盖 raw fixture -> full pipeline -> report
- [ ] CI 中存在至少 1 条真实 full pipeline test
- [ ] Typecheck/lint 通过

### US-017: 为重跑稳定性增加 deterministic regression checks
**描述：** 作为维护者，我想验证同一 fixture 重跑后 patch 与知识对象 ID 稳定，以便后续 diff 和 review 不会被噪音主导。

**Acceptance Criteria：**
- [ ] 同一 fixture 重跑时 `patch_id` 稳定
- [ ] 同一 fixture 重跑时 `entity_id`、`claim_id` 稳定
- [ ] 失败 run 也会保留 debug artifacts 便于对比
- [ ] 稳定性检查进入 automated tests
- [ ] Typecheck/lint 通过

### Milestone 6: 让 skills、页面编译与文档叙事对齐

### US-018: 为 domain skills 增加真实 runtime entrypoints
**描述：** 作为 agent 使用者，我想让 domain skills 能映射到真实系统入口，以便 skills 不是说明书，而是可执行单元。

**Acceptance Criteria：**
- [ ] 每个 domain skill 都映射到真实 runtime entrypoint，例如 route、parse、extract、patch、lint、review
- [ ] skills 文档与 runtime 行为保持一致
- [ ] 每个 domain skill 都有 contract tests 覆盖 input、output、invariants、fallback、evaluation
- [ ] Typecheck/lint 通过

### US-019: 补齐 8 类页面类型的真实编译覆盖
**描述：** 作为 wiki 维护者，我想让 8 类页面类型都有真实 compile path 和 tests，以便页面模型不是半闭环。

**Acceptance Criteria：**
- [ ] `parser` 页面类型有真实 compile path
- [ ] `benchmark` 页面类型有真实 compile path
- [ ] `source`、`entity`、`concept`、`failure`、`comparison`、`decision` 继续可用
- [ ] 8 类页面均有测试
- [ ] frontmatter/body schema 稳定
- [ ] Typecheck/lint 通过

### US-020: 增强 run 可观测性与调试资产
**描述：** 作为维护者，我想让任何 run 都能快速追到 route、parser、fallback、lint、harness、review 细节，以便排障和复盘成本可控。

**Acceptance Criteria：**
- [ ] `RunManifest` 中记录 selected route、parser chain、fallback_used、lint summary、harness summary、gate decision、review status
- [ ] 每个 stage 记录 `started_at`、`finished_at`、`duration_ms`、warnings、`error_detail`
- [ ] debug assets 至少包括 route log、parser raw result、fallback trace、repair log、lint findings、harness report
- [ ] 任意失败 run 都能从 report 快速定位阶段和原因
- [ ] Typecheck/lint 通过

### US-021: 治理 README、schema artifacts 与实现一致性
**描述：** 作为新加入的开发者，我想通过 README 和 schema artifacts 正确理解系统能力边界，以便不会被“文档领先实现”误导。

**Acceptance Criteria：**
- [ ] README 中的命令、流程、page types、parser 列表与当前实现一致
- [ ] roadmap 项目被明确标注，不伪装成已完成能力
- [ ] 导出并维护 `doc.schema.json`、`page.schema.json`、`patch.schema.json` 或等效 schema artifacts
- [ ] README 中声明的每个 CLI 命令都可运行
- [ ] Typecheck/lint 通过

## Functional Requirements

- FR-1: 系统必须提供统一的 pipeline 执行入口，能够贯穿 ingest 到 report
- FR-2: 系统必须为每次运行生成真实 `run_id` 和 `RunManifest`
- FR-3: 每个阶段都必须读写真实 artifacts，并更新自己的阶段状态
- FR-4: `parse` 阶段必须通过 `Route + ParserRegistry + Orchestrator` 执行 parser chain
- FR-5: router config 中声明的 parser 必须全部能被 runtime registry resolve
- FR-6: signal extractor 必须提供真实可验证的 dual-column、formula、OCR 等 routing signals
- FR-7: route scoring 的规则必须明确、文档化，并与代码实现一致
- FR-8: 所有 wiki state 变更都必须通过正式 patch 进入系统
- FR-9: `patch_id` 必须是确定性的、可重复生成的
- FR-10: patch 必须支持 apply、merge、rollback、reject 生命周期
- FR-11: lint 必须消费真实 wiki / knowledge / patch artifacts
- FR-12: harness 和 gate 必须消费真实 artifacts 并输出正式 release decision
- FR-13: 系统必须用 raw fixtures 跑通至少一条真实 full pipeline regression
- FR-14: 同一输入重复运行时必须能验证 patch 与知识对象 ID 稳定性
- FR-15: domain skills 必须有真实 runtime entrypoints 和 contract tests
- FR-16: 8 类页面类型都必须具备 compile path 与测试覆盖
- FR-17: `RunManifest` 与 report 必须提供足够的可观测性和调试资产
- FR-18: README、schema artifacts、CLI 说明必须与当前实现一致

## Non-Goals

- 本轮不优先做花哨 UI 或 review console
- 本轮不优先扩很多新的 parser adapter
- 本轮不优先做复杂 agent orchestration
- 本轮不优先做通用平台化抽象
- 本轮不优先引入大规模 hybrid / LLM-assisted extraction

## Design Considerations

- 优先以 artifact-driven pipeline 替代“命令存在但闭环未成”的状态
- patch 必须成为 state transition center，而不是 compiler 附属物
- route/parse 的设计以 deterministic、config/runtime 对齐为先
- regression fixtures 要从 raw input 开始，而不是从中间对象伪造开始
- skills 必须与 runtime entrypoints 一一对应，避免“文档即能力”的错觉

## Technical Considerations

- 当前仓库已存在 `run_store`、`ir_store`、`knowledge_store`、`artifact_stores`、`signal_extractor` 等模块，可作为本轮闭环化的基础
- `configs/router.yaml` 与 `ParserRegistry` 的一致性必须成为启动期或测试期硬校验
- patch 的确定性哈希需要基于 canonical 内容，而不是 Python 运行时哈希
- `RunManifest` 是 report、gate、review、debug trace 的单一追溯入口，设计上必须可持久化且可恢复
- regression 测试必须覆盖 success path 和 failure path，两者都要保留可定位 artifacts

## Success Metrics

- 存在一条从 raw fixture 到 report 的真实可执行金路径
- `parse` 不再绕过 router、registry、orchestrator
- router config 与 runtime parser 完全对齐
- dual-column 与 formula-heavy 能真实影响 route 选择
- patch 成为正式状态转换层，并支持确定性 `patch_id`
- lint、harness、gate 基于真实 artifacts 生效
- CI 中至少存在 1 条 full pipeline regression test
- domain skills 有 runtime entrypoints 和 contract tests
- README 与实际实现一致，不再夸大已完成能力

## Open Questions

- 统一执行入口最终采用 `docos run <file_path>` 还是 `docos pipeline run <source_id>`
- parser strategy 选择“缩减 router.yaml 到当前实现”还是“补齐所有已声明 adapter”
- OCR fixture 首版采用真实 PDF、图片输入，还是模拟 OCR-like PDF
- schema artifacts 采用 JSON Schema 导出、YAML 描述，还是两者都保留
- skills runtime 化是优先走 CLI entrypoint，还是抽象出独立 service layer
