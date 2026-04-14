# 专业 Document Parsing Wiki 系统需求说明书（requirements.md）

- 文档名称：Professional Document Parsing Wiki Requirements
- 版本：v1.0
- 状态：Draft
- 日期：2026-04-13
- 适用对象：产品负责人、架构师、Parser 工程师、LLM 工程师、知识工程师、审阅人员、平台工程团队

---

## 1. 文档目的

本文档定义一套“专业的、可验证的、可维护的” **LLM Wiki + Harness 驱动的 Document Parsing Wiki 系统**的完整需求。

该系统的目标不是做一个“会把 PDF 变成 Markdown 的脚本”，也不是做一个“靠大模型自动写笔记”的玩具系统，而是构建一个 **从原始文档到证据化知识库的编译系统（document-to-knowledge compiler）**：

```text
Raw Sources -> Parser Router -> Canonical DocIR -> Claim/Entity Graph -> Markdown Wiki -> Review & Harness
```

本需求文档用于统一以下内容：

1. 产品边界与系统目标
2. 信息架构与核心数据模型
3. Skills 设计与运行约束
4. Harness / Evaluation 体系
5. 人机协作审阅机制
6. 非功能性要求、验收标准与实施路线

---

## 2. 项目背景与问题定义

### 2.1 背景

Karpathy 的 LLM Wiki 给出了一个极强的模式：  
**Markdown 文件 + LLM + Schema + Obsidian**。

这个模式的优点是：

- 门槛低
- 结构清晰
- 人机共读
- 便于用 Git 管理
- 便于增量演化

但对于 **专业 document parsing** 场景，仅有这些还不够。原因在于：

1. 文档解析不是纯文本问题，而是 **版面、结构、证据、引用、表格、公式、阅读顺序** 的综合问题。
2. 纯 Markdown 无法完整保留 parsing 过程中需要的几何和结构信息。
3. 没有 harness 的 LLM Wiki 很难形成可验证的执行质量。
4. 没有显式 schema 与 patch 机制，系统容易在重复导入、多次更新后逐步失控。
5. 没有审阅台，错误无法高效定位，解析失败模式无法沉淀。

因此，本项目的核心判断是：

> 护城河不在“LLM Wiki 这个模式”，而在“谁能把这个模式工程化为可验证、可回归、可维护的知识编译系统”。

### 2.2 核心问题

本项目要解决的问题包括：

- 如何将异构文档（PDF、DOCX、PPTX、HTML 等）稳定转换为统一结构？
- 如何避免过早把信息压扁成 Markdown，导致丢失证据和几何信息？
- 如何将 parser 输出转化为“有证据锚点”的 claim / entity / concept 图谱？
- 如何让 LLM 参与整理知识，但不失去可追溯性与可控性？
- 如何用 harness 保证每次 ingest 都可评估、可比较、可回归？
- 如何让 Markdown/Obsidian 仍然保持一流的人类浏览体验？

### 2.3 产品定位

本系统定位为：

> 一个面向专业文档解析与知识维护场景的 **证据优先型 LLM Wiki 操作系统**。

它不是单纯的：

- OCR 工具
- PDF 转 Markdown 工具
- 问答机器人
- 个人笔记系统
- 单次抽取脚本

它应该是一个长期运行的、支持增量维护的、能被团队共同使用的知识基础设施。

---

## 3. 设计目标与原则

### 3.1 总体目标

系统必须满足以下总目标：

1. **可验证**：任何知识页中的关键结论都能够追溯到原始文档证据。
2. **可维护**：重复 ingest、schema 升级、parser 替换时，系统仍可稳定运行。
3. **可扩展**：支持新增 parser、新增文档类型、新增 page type、新增 skill。
4. **可审阅**：高风险 patch 必须可视化审阅，而非直接覆盖。
5. **可评估**：系统每次运行必须生成结构化报告，并进入 harness 体系。
6. **可协作**：既适合 LLM，也适合人类在 Markdown / Wiki / Review Console 中共同工作。

### 3.2 设计原则

#### P1. Raw Source 是法律意义上的最终真相
原始文档必须保留，不可被覆盖，不可由 LLM 修改。

#### P2. DocIR 是机器处理的规范真相
系统内部处理的规范对象必须是 **Canonical DocIR**，而不是 Markdown。

#### P3. Markdown 是面向人类与 LLM 的视图层
Markdown 应用于阅读、导航、检索、Git diff、Obsidian 浏览，但不应作为唯一机器真相。

#### P4. 所有知识必须有证据锚点
每条关键 claim 都必须链接回 source anchor。

#### P5. LLM 只生成 patch，不直接改写正式库
系统必须采用 `generate patch -> lint -> review -> merge` 模式。

#### P6. Skills 必须是窄、可测、typed 的
不得依赖一个无法解释的大总管 prompt。

#### P7. Harness 必须是发布门禁
没有通过 harness 的结果不得自动 merge。

#### P8. 人机协同优先于纯自动化
低置信度、高风险、跨页复杂结构、冲突知识必须进入 review queue。

---

## 4. 术语表

| 术语 | 定义 |
|---|---|
| Raw Source | 原始文档文件，如 PDF/DOCX/PPTX/HTML/image 等 |
| Parser | 文档解析引擎，负责从 Raw Source 中提取结构、文本、布局、表格、公式等 |
| Parser Router | 依据文档类型与复杂度，选择合适解析策略的调度模块 |
| DocIR | Canonical Document Intermediate Representation，系统内部标准文档表示 |
| Block | DocIR 中的最小结构单元，如标题、段落、列表、表格、公式、图注等 |
| Evidence Anchor | 指向原始文档某页、某块、某位置的证据锚点 |
| Claim | 可被支持、推断或冲突标记的知识陈述 |
| Entity | 被识别出的实体对象，如人、组织、方法、数据集、术语、系统等 |
| Wiki Page | 面向人类和 LLM 的知识页，通常为 Markdown 文件 |
| Patch | 对 wiki 或结构化数据的变更提案，而非直接写入 |
| Harness | 用于验证解析质量、知识质量、维护质量和用户体验的评测体系 |
| Golden Set | 人工构建的高质量评测样本集 |
| Blast Radius | 一次 patch 波及的页面数、claim 数、链接数等影响范围 |
| Review Queue | 需要人工审阅的 patch 集合 |

---

## 5. 产品范围

### 5.1 In Scope（v1 必须覆盖）

1. PDF 文档 ingest
2. 可扩展支持 DOCX / PPTX / HTML
3. 多 parser 路由与可插拔 parser backend
4. Canonical DocIR 生成、归一化与版本化
5. Claim / Entity / Concept 抽取
6. Markdown Wiki 生成与增量更新
7. 证据锚点管理
8. Patch、lint、review、merge 流程
9. Harness 与评测报告
10. Review Console 与 Obsidian/Markdown 工作区协作
11. 失败模式沉淀与 parser 对比页
12. 变更审计、日志与可回归运行

### 5.2 Out of Scope（v1 不要求）

1. 纯端到端无人值守全自动发布
2. 面向公众的多租户 SaaS 商业计费系统
3. 通用搜索引擎替代
4. 实时网页抓取与持续网络爬虫
5. 通用知识图谱平台的全部能力
6. 复杂权限矩阵到企业 IAM 深度集成
7. 任意多语言高质量全覆盖（v1 优先中文/英文）
8. 高级 agent swarm 编排

### 5.3 优先支持文档类型

#### Phase 1
- 学术论文 PDF
- 技术报告 PDF
- 评测报告 PDF
- 产品/架构文档 PDF

#### Phase 2
- DOCX
- PPTX
- HTML
- 图片扫描文档

---

## 6. 目标用户与角色

### 6.1 知识工程师
负责定义 schema、page type、知识组织方式与命名规范。

### 6.2 Parser 工程师
负责 parser backend 接入、router 策略、DocIR 质量、结构归一化。

### 6.3 LLM 工程师
负责 skill 设计、prompt contract、patch 生成、知识抽取与冲突检测。

### 6.4 审阅者 / Domain Reviewer
负责审核复杂表格、公式、冲突 claim、高影响 patch。

### 6.5 产品负责人 / 架构师
负责范围控制、验收标准、目标指标与迭代路线。

### 6.6 最终使用者
以 Markdown/Obsidian/Wiki 的方式浏览知识，并通过 review console 查看证据。

---

## 7. 核心使用场景

### 7.1 新文档导入
用户上传一份 PDF，系统自动：

1. 创建 source record
2. 选择 parser route
3. 生成 DocIR
4. 生成 source summary page
5. 抽取 entities / claims / concepts
6. 生成 wiki patch
7. 运行 harness 与 lint
8. 根据策略自动 merge 或进入 review queue

### 7.2 重复导入 / 重跑
同一文档在 parser 版本升级后重新 ingest，系统必须：

- 识别同一 source
- 记录 parser_version 变化
- 计算差异
- 只提交增量 patch
- 输出 regression report

### 7.3 知识更新
新的 source 可能修正旧页面中的结论，系统必须：

- 更新相关 page
- 标记冲突 claim
- 记录 evidence 差异
- 不得默默覆盖历史结论

### 7.4 失败模式沉淀
当 parsing 失败时，系统应自动生成或更新 failure page，例如：

- 双栏阅读顺序错乱
- 跨页表格断裂
- 图表 caption 归属错误
- 公式被 OCR 污染
- footnote 漂移

### 7.5 Parser 对比
用户可查看某份文档在不同 parser 下的表现差异，包括：

- 文本 fidelity
- heading tree
- reading order
- table structure
- formula fidelity
- time/cost

---

## 8. 总体架构要求

### 8.1 架构概览

```text
                +----------------------+
                |     Raw Sources      |
                +----------+-----------+
                           |
                           v
                +----------------------+
                |    Source Registry    |
                +----------+-----------+
                           |
                           v
                +----------------------+
                |    Parser Router      |
                +----------+-----------+
                           |
          +----------------+----------------+
          |                                 |
          v                                 v
+----------------------+         +----------------------+
|  Parser Backend A    |         |  Parser Backend B    |
+----------+-----------+         +----------+-----------+
           \                                 /
            \                               /
             v                             v
                +----------------------+
                |   Normalization /    |
                |     Canonical DocIR  |
                +----------+-----------+
                           |
                           v
                +----------------------+
                | Claim / Entity Graph |
                +----------+-----------+
                           |
                           v
                +----------------------+
                | Patch Generation      |
                +----------+-----------+
                           |
                           v
                +----------------------+
                | Lint / Harness / QA   |
                +-----+-----------+----+
                      |           |
               auto merge     review queue
                      |           |
                      v           v
             +---------------------------+
             | Markdown Wiki + UI Layer  |
             +---------------------------+
```

### 8.2 逻辑层

系统必须包含以下逻辑层：

1. **Source Layer**：管理原始文档与元数据
2. **Parsing Layer**：完成 parser 选择、执行与 fallback
3. **DocIR Layer**：完成统一标准表示、结构修复与版本化
4. **Knowledge Layer**：完成 claims/entities/concepts 生成与维护
5. **Wiki Layer**：生成 Markdown 页面与导航结构
6. **QA Layer**：执行 lint、harness、差异分析与风险评估
7. **Review Layer**：支持人工审阅、批准、驳回、回滚
8. **Observability Layer**：日志、指标、trace、审计

---

## 9. 信息架构与目录结构要求

系统应采用清晰、可 Git 管理、可本地运行、可审阅 diff 的目录结构。

### 9.1 推荐目录

```text
project-root/
  raw/
    <source_id>/
      original.pdf
      attachments/
  parsed/
    <source_id>/
      <parser_name>/
        raw_output.json
        logs.json
        screenshots/
  ir/
    <source_id>.json
  graph/
    entities.jsonl
    claims.jsonl
    relations.jsonl
  wiki/
    index.md
    log.md
    sources/
    entities/
    concepts/
    parsers/
    benchmarks/
    failures/
    comparisons/
    decisions/
  patches/
    <run_id>.patch.json
  evals/
    golden/
    configs/
    runs/
  reviews/
    queue/
    approved/
    rejected/
  reports/
    ingest/
    regression/
  schemas/
    doc.schema.json
    page.schema.yaml
    patch.schema.json
    eval.schema.json
  configs/
    router.yaml
    thresholds.yaml
    skills/
  AGENTS.md
  OPS.md
  README.md
```

### 9.2 目录要求

1. `raw/` 必须只读。
2. `ir/` 必须保存每个 source 的标准化 DocIR。
3. `parsed/` 必须保留 parser 原始输出，便于调试与回归。
4. `wiki/` 必须是人类可读、可 diff、可链接的 Markdown 工作区。
5. `patches/` 必须记录每次变更提案。
6. `reports/` 必须提供可审计的 ingest 质量报告。
7. `schemas/` 必须版本化。
8. `configs/` 必须显式化而非硬编码到 prompt。

---

## 10. 数据分层与真相管理

### 10.1 四层真相

系统必须明确以下四层真相：

1. **Raw Source Truth**  
   法律和原始证据层，最终不可替代来源。

2. **DocIR Truth**  
   机器处理层，统一承载结构、布局、引用、表格、公式、阅读顺序等信息。

3. **Knowledge Truth**  
   Claim / Entity / Relation 层，面向知识维护。

4. **Wiki View Truth**  
   Markdown 呈现层，面向人类阅读与 LLM 协作。

### 10.2 约束

- Wiki 中出现的关键结论，必须能映射回 Knowledge Truth。
- Knowledge Truth 中的 supported claim，必须能映射回 DocIR Anchor。
- DocIR Anchor，必须能映射回 Raw Source 的页级/块级位置。
- 任一层不得假装自己是唯一真相。

---

## 11. Canonical DocIR 需求

### 11.1 DocIR 的目标

DocIR 必须作为 parser 结果的统一抽象，满足以下要求：

1. 支持多 parser 输出归一化
2. 保留版面、顺序、结构、证据位置信息
3. 支持增量修复与重新生成
4. 支持引用、脚注、表格、公式等复杂对象
5. 支持向 Markdown / HTML / JSON 等多种视图导出

### 11.2 DocIR 顶层字段（必须）

```json
{
  "doc_id": "string",
  "source_id": "string",
  "source_uri": "string",
  "mime_type": "application/pdf",
  "parser": "string",
  "parser_version": "string",
  "schema_version": "string",
  "created_at": "timestamp",
  "language": ["zh", "en"],
  "page_count": 12,
  "pages": [],
  "blocks": [],
  "relations": [],
  "warnings": [],
  "confidence": 0.0
}
```

### 11.3 Page 对象字段（必须）

每个 page 至少应包含：

- `page_no`
- `width`
- `height`
- `rotation`
- `image_uri` 或等价渲染引用
- `ocr_used`
- `reading_order_version`
- `blocks`
- `warnings`

### 11.4 Block 对象字段（必须）

每个 block 至少应包含：

- `block_id`
- `page_no`
- `block_type`
- `reading_order`
- `bbox`
- `parent_id`
- `children_ids`
- `text_plain`
- `text_md`
- `text_html`（如适用）
- `latex`（如适用）
- `table_cells`（如适用）
- `caption_target`（如适用）
- `footnote_refs`
- `citations`
- `confidence`
- `source_parser`
- `source_node_id`

### 11.5 支持的 block_type（v1）

- `title`
- `heading`
- `paragraph`
- `list`
- `list_item`
- `table`
- `table_cell`
- `figure`
- `caption`
- `equation`
- `equation_block`
- `footnote`
- `reference_item`
- `code_block`
- `quote`
- `header`
- `footer`
- `page_number`
- `unknown`

### 11.6 Relations（必须）

DocIR 必须支持 relations，例如：

- `caption_of`
- `footnote_of`
- `continued_from`
- `continued_to`
- `references`
- `mentioned_in`
- `same_table_as`
- `same_section_as`
- `duplicate_of`
- `derived_from`

### 11.7 DocIR 约束

1. 所有 block_id 必须唯一。
2. 同一 page 内 reading_order 不得重复。
3. bbox 必须是合法矩形坐标。
4. 表格必须区分逻辑结构与展示结构。
5. 跨页对象必须保留 continuity relation。
6. 任何修复流程不得删除原 parser 结果，只能新增规范结果或修复记录。
7. DocIR 必须可序列化为 JSON，并通过 schema 校验。

---

## 12. Source Registry 需求

### 12.1 Source Record 字段

每个 source 必须至少记录：

- `source_id`
- `source_hash`
- `file_name`
- `mime_type`
- `byte_size`
- `created_at`
- `ingested_at`
- `ingest_count`
- `language_hint`
- `origin`
- `tags`
- `owner`
- `status`
- `latest_run_id`
- `latest_docir_id`

### 12.2 Source Registry 功能要求

1. 支持通过 hash 去重。
2. 支持同一 source 多次 ingest。
3. 支持一个 source 多个 parser run 记录。
4. 支持 source 与 wiki pages 的双向索引。
5. 支持 source 与 review issue 的关联。
6. 支持源文件不可变存储。

---

## 13. Parser Router 需求

### 13.1 目标

Parser Router 负责根据文档特征与策略配置选择适合的 parser 路线。

### 13.2 Router 输入

Router 至少应接收以下信号：

- 文件类型
- 页数
- 是否扫描件
- 是否双栏
- 是否表格密集
- 是否公式密集
- 是否图像密集
- 语言类型
- 是否需 OCR
- 是否历史上有失败模式
- 目标输出模式（高保真 / 高吞吐 / 低成本）

### 13.3 Router 输出

Router 必须输出：

- `selected_route`
- `primary_parser`
- `fallback_parsers`
- `expected_risks`
- `post_parse_repairs`
- `review_policy`

### 13.4 路由策略要求

1. 必须可配置，不得硬编码到 prompt。
2. 必须支持单 parser 与 ensemble parser 路线。
3. 必须支持 page-level 或 block-level repair 策略。
4. 必须记录路由原因，便于调试。
5. 必须支持 parser 不可用时的降级。

### 13.5 路由模式（v1）

- `fast_text_route`
- `complex_pdf_route`
- `ocr_heavy_route`
- `table_formula_route`
- `fallback_safe_route`

---

## 14. Parsing Pipeline 需求

### 14.1 两段式解析

系统必须采用两段式解析：

#### Stage A：Page-local Parse
按页高保真提取：

- 文本
- layout
- reading order
- table
- formula
- caption
- footnote

#### Stage B：Document-global Repair
跨页修复：

- heading tree
- section hierarchy
- 跨页表格
- 跨页脚注/引用
- 重复 header/footer 去噪
- 实体统一命名
- 图注归属修正

### 14.2 Parser Backend 要求

系统必须支持可插拔 backend，至少抽象出以下统一接口：

- `parse(file) -> raw_result`
- `normalize(raw_result) -> partial_docir`
- `export_debug_assets(...)`
- `healthcheck()`
- `capabilities()`

### 14.3 Fallback 要求

当 primary parser 失败时，系统应：

1. 记录失败原因
2. 自动调用 fallback parser
3. 标记 fallback_used
4. 进入更严格的 review policy
5. 生成 parser comparison report

### 14.4 调试资产要求

解析阶段必须保留以下资产：

- 原始 parser 输出
- 渲染页图
- block overlay
- reading order overlay
- warnings
- parser log
- time/cost 统计

---

## 15. Normalization 需求

### 15.1 结构归一化目标

Normalization 负责将不同 parser 的结构结果统一到 Canonical DocIR。

### 15.2 归一化规则（必须）

1. Heading 层级必须标准化。
2. List/ListItem 关系必须标准化。
3. Table 必须区分 header/body/footer。
4. Equation 应保留原始表达与渲染表达。
5. Caption 必须绑定 figure/table target。
6. Footnote 与正文引用必须建立 relation。
7. Reference list 必须作为独立结构对象保存。
8. Header/Footer/Page number 必须可选过滤。
9. 双栏/多栏阅读顺序必须显式保存。
10. Unknown block 不得静默丢弃。

### 15.3 Repair 记录要求

每一次 normalization / repair 必须记录：

- `repair_id`
- `repair_type`
- `before`
- `after`
- `reason`
- `confidence`
- `performed_by`（rule / model / human）
- `timestamp`

---

## 16. Claim / Entity / Relation 抽取需求

### 16.1 总体要求

系统必须从 DocIR 中抽取结构化知识对象，而不是只生成自由文本总结。

### 16.2 Entity 类型（v1）

- person
- organization
- product
- model
- method
- benchmark
- dataset
- concept
- metric
- parser
- failure_mode
- decision
- document

### 16.3 Claim 模型（必须）

每条 claim 至少包含：

- `claim_id`
- `statement`
- `subject_entity_id`
- `predicate`
- `object`
- `page_refs`
- `evidence_anchors`
- `status`
- `confidence`
- `supporting_sources`
- `conflicting_sources`
- `inference_note`
- `updated_at`

### 16.4 Claim 状态

系统必须支持：

- `supported`
- `inferred`
- `conflicted`
- `deprecated`
- `needs_review`

### 16.5 抽取原则

1. 不得只生成无法追溯的“漂亮总结”。
2. 关键 claim 必须绑定至少一个 evidence anchor。
3. 推断类 claim 必须显式标注 `inferred`。
4. 冲突 claim 不得被静默覆盖。
5. 同义实体必须进行 candidate-level dedup，而非直接粗暴合并。

---

## 17. Wiki Page 类型与模板需求

### 17.1 必须支持的 page type（v1）

1. `source`
2. `entity`
3. `concept`
4. `parser`
5. `benchmark`
6. `failure`
7. `comparison`
8. `decision`

### 17.2 每类 page 的最低要求

#### Source Page
必须包含：

- source metadata
- ingest status
- parser route
- high-level summary
- section outline
- extracted entities
- key claims
- known warnings
- links to evidence / review report

#### Entity Page
必须包含：

- canonical name
- aliases
- entity type
- defining description
- related claims
- supporting sources
- related entities
- open questions

#### Concept Page
必须包含：

- concept definition
- boundary / non-goals
- related methods/systems
- claims and evidence
- comparison notes
- unresolved issues

#### Parser Page
必须包含：

- parser profile
- capability summary
- strengths/weaknesses
- known failure modes
- benchmark performance notes
- recommended routes

#### Failure Page
必须包含：

- failure definition
- trigger patterns
- examples
- impacted parsers
- repair strategy
- review checklist

#### Comparison Page
必须包含：

- compared objects
- comparison dimensions
- evidence-backed differences
- open uncertainty
- recommendation

#### Decision Page
必须包含：

- decision statement
- context
- alternatives
- rationale
- consequences
- review date

### 17.3 Frontmatter 需求

所有 wiki page 必须有 frontmatter，至少包含：

```yaml
id: string
type: source|entity|concept|parser|benchmark|failure|comparison|decision
title: string
status: draft|auto|reviewed|approved|deprecated
schema_version: string
created_at: 2026-04-13
updated_at: 2026-04-13
source_docs: []
related_entities: []
related_claims: []
review_status: pending|not_needed|approved|rejected
```

### 17.4 链接与命名规范

1. Page 文件名必须稳定可复现。
2. 支持 slug 与 human title 分离。
3. wiki link 必须优先使用 stable id。
4. rename 时必须支持重定向或 alias。
5. orphan page 必须进入 lint 报告。

---

## 18. Evidence Anchor 与可追溯性需求

### 18.1 Evidence Anchor 模型

每个 anchor 至少应包含：

- `anchor_id`
- `source_id`
- `doc_id`
- `page_no`
- `block_id`
- `bbox`
- `char_start`
- `char_end`
- `quote`（可选短摘录）
- `render_uri`
- `confidence`

### 18.2 追溯要求

1. Source Page 中的 key claims 必须能点回原文位置。
2. Entity / Concept Page 中的核心定义必须具备 anchor。
3. 任何 `supported` claim 必须至少有一个 anchor。
4. `inferred` claim 必须给出推理说明与支持 anchors。
5. `conflicted` claim 必须同时列出支持与冲突证据。

### 18.3 锚点稳定性要求

- 当 page image 重新渲染时，anchor 不应失效。
- 当 parser 升级导致 block_id 变化时，系统必须尝试 anchor remap。
- remap 失败时必须标记 `anchor_stale`。

---

## 19. Patch 工作流需求

### 19.1 基本原则

系统不得直接覆盖正式 wiki，必须通过 patch 流程变更。

### 19.2 Patch 内容

每个 patch 必须至少包含：

- `patch_id`
- `run_id`
- `source_id`
- `generated_at`
- `changes[]`
- `blast_radius`
- `risk_score`
- `lint_result`
- `harness_result`
- `review_required`
- `merge_status`

### 19.3 Change 类型

- create_page
- update_page
- split_page
- merge_page
- add_claim
- update_claim
- deprecate_claim
- relink_entity
- add_alias
- fix_anchor
- mark_conflict

### 19.4 Patch 策略

1. 小范围、低风险 patch 可自动 merge。
2. 涉及多个核心 page 的 patch 必须进入 review。
3. 大规模实体重命名必须进入 review。
4. 删除内容必须严格受控。
5. 任何 unsupported claim 增加不得自动 merge。

### 19.5 Blast Radius 计算

blast radius 至少应考虑：

- 影响页面数
- 新增/变更 claims 数
- 断链数
- 实体重定向数
- 冲突增加数

---

## 20. Skills 设计需求

本系统必须将核心能力拆解为窄而明确的 skills。每个 skill 必须声明输入、输出、约束、失败策略与评估方式。

### 20.1 Skill 总表

| Skill 名称 | 目标 |
|---|---|
| route_document | 选择合适解析路线 |
| parse_to_docir | 调 parser 并生成初始 DocIR |
| normalize_structure | 统一结构与跨页修复 |
| extract_entities_claims | 抽取知识对象 |
| compile_source_page | 生成/更新 source summary page |
| update_knowledge_pages | 更新 entity/concept/comparison/failure 等页面 |
| lint_reconcile | 检查 schema、链接、冲突、重复与 unsupported claim |
| run_harness_publish_report | 运行评测并给出发布建议 |

---

## 21. Skill Contract 详细要求

### 21.1 `route_document`

### 目标
选择最适合该文档的解析路线。

### 输入
- source metadata
- file features
- historical failure patterns
- router config

### 输出
- selected route
- parser plan
- review policy

### Invariants
- 不得输出空 route
- 必须可解释
- 必须保留 fallback 计划

### Fallback
- 若特征识别失败，使用 `fallback_safe_route`

### 通过标准
- 路由结果可复现
- 路由日志完整
- route 与 parser config 一致

---

### 21.2 `parse_to_docir`

### 目标
执行 parser 并生成初始 DocIR。

### 输入
- source file
- parser plan

### 输出
- raw parser output
- partial DocIR
- parse logs
- debug assets

### Invariants
- 不得丢失 raw output
- DocIR 必须有 page 与 block 基本结构
- 失败必须显式返回 error state

### Fallback
- primary parser 失败后自动切 fallback parser
- 进入 stricter review mode

### 通过标准
- schema 校验通过
- 必填字段完整
- debug assets 可用

---

### 21.3 `normalize_structure`

### 目标
统一结构、修复阅读顺序与跨页对象。

### 输入
- partial DocIR
- normalization rules

### 输出
- canonical DocIR
- repair records
- warnings

### Invariants
- 修复必须可审计
- 不得静默删除 unknown block
- 不得打断 anchor 追溯

### Fallback
- 低置信度修复标记 `needs_review`

### 通过标准
- heading tree 合法
- table/equation/caption 结构合法
- continuity relation 建立成功

---

### 21.4 `extract_entities_claims`

### 目标
从 DocIR 中抽取结构化知识对象。

### 输入
- canonical DocIR
- ontology config
- entity normalization config

### 输出
- entities
- claims
- relations
- open questions

### Invariants
- supported claim 必须有 evidence
- inferred claim 必须有 inference note
- conflicted claim 不得覆盖旧 claim

### Fallback
- 低置信度抽取进入 review queue

### 通过标准
- claim schema 通过校验
- evidence coverage 达标
- duplicate entity 低于阈值

---

### 21.5 `compile_source_page`

### 目标
生成或更新 source summary page。

### 输入
- source metadata
- DocIR
- extracted entities/claims

### 输出
- source page markdown
- page frontmatter
- evidence index

### Invariants
- 必须包含 warnings 与 parser route
- 关键 claim 必须可追溯
- 不得输出无 frontmatter 页面

### Fallback
- 若结构不完整，输出 partial page 并标记 review

### 通过标准
- page schema 通过
- wiki links 有效
- section outline 合理

---

### 21.6 `update_knowledge_pages`

### 目标
更新实体、概念、比较、失败模式等页面。

### 输入
- entities
- claims
- existing wiki graph
- patch policy

### 输出
- page updates
- new pages
- merge/split suggestions

### Invariants
- 不得隐式合并冲突实体
- 不得删除历史决策记录
- 修改必须 patch 化

### Fallback
- 高 blast radius 自动 review

### 通过标准
- duplicate pages 未增加
- unsupported claim 未增加
- backlinks 保持健康

---

### 21.7 `lint_reconcile`

### 目标
执行结构与知识层 lint。

### 输入
- proposed patch
- wiki
- graph

### 输出
- lint report
- reconcile suggestions
- risk score

### Invariants
- 必须识别 orphan page、broken link、schema violation
- 必须识别 unsupported claim
- 必须识别 duplicate entity candidates

### Fallback
- 高风险 patch 阻止 auto merge

### 通过标准
- P0/P1 lint 无阻塞问题
- 风险分级正确
- 报告可审阅

---

### 21.8 `run_harness_publish_report`

### 目标
运行完整评测并给出发布建议。

### 输入
- run outputs
- golden set
- thresholds

### 输出
- harness report
- release decision
- regression summary

### Invariants
- 未跑 harness 不得自动 merge
- regression 不得被忽略
- 结果必须结构化保存

### Fallback
- harness 异常时禁止 auto merge

### 通过标准
- 报告完整
- 指标可比较
- release decision 可解释

---

## 22. Harness / 评测体系需求

### 22.1 总体目标

Harness 必须覆盖四类质量：

1. Parse Quality
2. Knowledge Quality
3. Maintenance Quality
4. UX / Workflow Quality

### 22.2 Parse Harness 指标（必须）

- text fidelity
- heading tree accuracy
- reading order accuracy
- table structure accuracy
- formula fidelity
- caption/footnote linkage accuracy
- OCR contamination rate
- parse completeness

### 22.3 Knowledge Harness 指标（必须）

- citation coverage
- unsupported claim rate
- hallucinated summary rate
- duplicate entity rate
- contradiction detection precision/recall
- page update minimality
- anchor validity rate

### 22.4 Maintenance Harness 指标（必须）

- broken wikilink count
- orphan page rate
- stale claim rate
- schema violation count
- patch blast radius distribution
- re-ingest diff stability
- regression failure count

### 22.5 UX Harness 指标（建议）

- time to first useful page
- average reviewer edits per doc
- review rejection rate
- review resolution time
- parser compare turnaround time

### 22.6 阈值管理

系统必须支持：

- 全局阈值
- page-type 阈值
- route-specific 阈值
- parser-specific 阈值
- dev/staging/prod 不同阈值

### 22.7 Golden Set 管理

1. Golden Set 必须版本化。
2. 每条样本必须有标注规范。
3. 必须覆盖复杂失败场景。
4. 必须支持 parser regression 比较。
5. 应包含 page-level 与 doc-level 两类样本。

---

## 23. Lint 规则需求

### 23.1 结构类 Lint

- frontmatter 缺失
- schema version 缺失
- invalid id
- duplicate id
- broken link
- orphan page
- invalid page type

### 23.2 知识类 Lint

- supported claim 无 evidence
- inferred claim 无推理说明
- conflicted claim 未列冲突来源
- entity alias 失配
- page 定义与 claim 集不一致

### 23.3 运维类 Lint

- parser version 未记录
- review 状态缺失
- patch 缺少 risk score
- old anchor stale 未处理
- report 丢失

### 23.4 Lint 级别

- P0：阻止发布
- P1：必须修复后 merge
- P2：可合并但需跟踪
- P3：建议优化

---

## 24. Review Console 需求

### 24.1 总体目标

Review Console 用于审阅复杂解析与高风险 patch，不得由纯 Markdown 替代。

### 24.2 必须支持的能力

1. 原始页面查看
2. bbox overlay
3. reading order overlay
4. block-level inspect
5. claim -> evidence drilldown
6. patch diff 查看
7. parser A/B compare
8. approve / reject / request changes
9. anchor stale 修复辅助
10. issue 注释与状态流转

### 24.3 审阅对象

以下对象必须可审阅：

- 复杂表格
- 复杂公式
- 跨页对象
- 冲突 claim
- 大 blast radius patch
- 实体合并操作
- 失败模式新增/更新

### 24.4 审阅操作日志

所有审阅操作必须记录：

- reviewer
- timestamp
- target object
- decision
- reason
- linked patch
- optional note

---

## 25. Markdown / Obsidian Workspace 需求

### 25.1 目标

保留 Markdown/Obsidian 的低门槛与高可读性优势，同时不把它当作唯一事实层。

### 25.2 必须支持

1. `index.md`：总导航页
2. `log.md`：更新日志页
3. 双向链接
4. frontmatter
5. tags / aliases
6. page template
7. parser/benchmark/failure 等专用目录
8. source page 与 evidence link 跳转

### 25.3 建议支持

- Dataview 或等价索引视图
- review backlog 视图
- stale pages 视图
- parser comparison 索引页

### 25.4 Markdown 生成要求

1. 不得生成不可读大段 JSON 垃圾。
2. 标题层级必须清晰。
3. 证据与结论应尽量邻近呈现。
4. 必须保留 page type 与 status。
5. 需要可 diff、可 merge、可回滚。

---

## 26. 知识维护与演化需求

### 26.1 增量更新

系统必须优先执行增量更新，而不是每次全量重写 wiki。

### 26.2 冲突管理

当新 source 与旧结论冲突时，系统必须：

1. 标记冲突
2. 列出两侧证据
3. 不得默默覆盖旧结论
4. 允许 reviewer 或后续 source 解决冲突

### 26.3 实体去重

实体 dedup 必须是候选式流程：

- candidate generation
- similarity scoring
- evidence review
- merge or keep separate

### 26.4 弃用策略

被后续证据否定或不再适用的内容必须支持：

- `deprecated` 标记
- 保留历史
- 指向替代页面或新结论

---

## 27. 配置与策略需求

### 27.1 配置必须外置

以下配置必须外置化：

- parser routes
- risk thresholds
- page templates
- ontology
- dedup rules
- lint rules
- release gates
- review policies

### 27.2 配置版本化

配置变更必须进入版本控制，并可关联到 run/report。

### 27.3 环境隔离

系统至少支持：

- local
- dev
- staging
- prod

环境之间的阈值、parser 可用性、merge 策略必须可区分。

---

## 28. API / CLI / 运行接口需求

### 28.1 CLI（v1 必须）

系统至少应提供以下命令能力：

- `ingest <file>`
- `route <source>`
- `parse <source>`
- `normalize <source>`
- `extract <source>`
- `compile <source>`
- `lint`
- `eval`
- `review list`
- `review approve <patch>`
- `review reject <patch>`
- `report <run>`

### 28.2 API（v1 可选）

建议提供：

- source upload API
- run status API
- patch inspection API
- report query API
- review action API

### 28.3 幂等性要求

同一 source、同一 parser config、同一 schema version 在重复运行时，结果应尽量稳定且可复现。

---

## 29. 观测性与审计需求

### 29.1 日志

每次 ingest run 必须记录：

- run_id
- source_id
- parser route
- parser versions
- timing breakdown
- warnings/errors
- patch summary
- review decision
- harness summary

### 29.2 Metrics

系统至少应输出：

- ingest_success_rate
- parser_failure_rate
- fallback_rate
- auto_merge_rate
- review_required_rate
- unsupported_claim_rate
- stale_anchor_rate
- average_time_to_first_page

### 29.3 Trace

建议支持贯穿一次 ingest 的 trace id。

### 29.4 审计

任何 merge/reject/rollback 都必须可追溯。

---

## 30. 安全与权限需求

### 30.1 数据安全

1. Raw source 不得被 LLM 直接覆写。
2. 需支持敏感文档本地运行。
3. 需支持 parser / LLM provider 配置隔离。
4. 应支持脱敏或 restricted mode。

### 30.2 权限分级（v1 建议）

- viewer
- reviewer
- editor
- admin

### 30.3 审批要求

高风险 patch、实体合并、批量重命名等操作应需要 reviewer 或 admin 批准。

---

## 31. 非功能性要求（NFR）

### 31.1 性能

- 单份中等复杂度文档应在可接受时间内生成首个可用 source page。
- 系统应支持批量 ingest。
- Review Console 打开单页渲染应低延迟。

### 31.2 可靠性

- 系统不得因单个 parser 失败导致整个 ingest 流程彻底失效。
- 任何中间失败应产生可恢复状态。
- raw/ir/wiki/report 之间的引用应保持一致。

### 31.3 可扩展性

- 新增 parser backend 不应要求重写全系统。
- 新增 page type 不应破坏现有 wiki。
- schema 升级应支持迁移策略。

### 31.4 可维护性

- 核心规则应尽量配置化。
- prompt 应与 skill contract 配套，而非散落。
- 失败模式应可沉淀为知识对象。

### 31.5 可解释性

- 任何 auto merge / review / reject 决策应可解释。
- route 选择应可解释。
- claim 状态应可解释。

### 31.6 可移植性

- 应支持本地文件系统部署。
- 应尽量避免对单一云服务的强绑定。

---

## 32. 功能需求清单（FR）

以下为 v1 功能需求基线。

### 32.1 Ingest 与 Source 管理

- **FR-001** 系统必须支持导入 PDF 文档。
- **FR-002** 系统必须为每个 source 分配稳定的 `source_id`。
- **FR-003** 系统必须通过 hash 检测重复文档。
- **FR-004** 系统必须保留原始文档不可变副本。
- **FR-005** 系统必须记录 source ingest 历史。

### 32.2 Router 与 Parser

- **FR-006** 系统必须在解析前执行 route 选择。
- **FR-007** 系统必须支持至少一个 primary parser 和一个 fallback parser。
- **FR-008** 系统必须记录 route 原因与 parser 版本。
- **FR-009** 系统必须支持 parser 失败降级。
- **FR-010** 系统必须输出 parser debug 资产。

### 32.3 DocIR 与归一化

- **FR-011** 系统必须生成 Canonical DocIR。
- **FR-012** DocIR 必须通过 schema 校验。
- **FR-013** 系统必须保存 page、block、relation 三级结构。
- **FR-014** 系统必须保存阅读顺序和 bbox。
- **FR-015** 系统必须支持跨页结构修复。
- **FR-016** 系统不得静默丢弃 unknown block。

### 32.4 知识抽取

- **FR-017** 系统必须抽取 entity、claim、relation。
- **FR-018** `supported` claim 必须具备 evidence anchor。
- **FR-019** `inferred` claim 必须具备推理说明。
- **FR-020** 冲突 claim 必须显式标记。
- **FR-021** 系统必须支持实体候选去重。

### 32.5 Wiki 编译

- **FR-022** 系统必须生成 source page。
- **FR-023** 系统必须支持 entity / concept page 更新。
- **FR-024** 系统必须为所有页面写入 frontmatter。
- **FR-025** 系统必须生成稳定的 wiki link。
- **FR-026** 系统必须支持 failure / parser / comparison / decision page。

### 32.6 Patch / Lint / Review

- **FR-027** 系统必须通过 patch 更新 wiki。
- **FR-028** 系统必须计算 patch risk score 与 blast radius。
- **FR-029** 系统必须运行结构与知识 lint。
- **FR-030** 高风险 patch 必须进入 review queue。
- **FR-031** 系统必须支持 approve / reject / rollback。

### 32.7 Harness / Report

- **FR-032** 系统必须对每次 ingest 运行 harness。
- **FR-033** 系统必须生成 ingest report。
- **FR-034** 系统必须支持 regression 比较。
- **FR-035** 未通过发布门禁的结果不得 auto merge。
- **FR-036** 系统必须可查询历史 run 报告。

### 32.8 UX 与可视化

- **FR-037** 系统必须提供 Markdown Wiki 工作区。
- **FR-038** 系统必须提供 Review Console。
- **FR-039** Review Console 必须支持 evidence drilldown。
- **FR-040** 系统必须支持 parser A/B compare。
- **FR-041** 系统必须提供 review backlog 视图。

---

## 33. 非功能需求清单（NFR）

- **NFR-001** 系统必须保证 raw source 不可变。
- **NFR-002** 系统必须支持 schema versioning。
- **NFR-003** 系统必须支持 parser versioning。
- **NFR-004** 系统必须保证 ingest 流程可审计。
- **NFR-005** 系统必须保证关键知识可追溯。
- **NFR-006** 系统应尽量保证重复运行结果稳定。
- **NFR-007** 系统应支持本地运行模式。
- **NFR-008** 系统应支持离线/受限网络环境。
- **NFR-009** 系统应支持增量更新。
- **NFR-010** 系统应支持可插拔 backend。
- **NFR-011** 系统应支持多语言扩展。
- **NFR-012** 系统应支持运行日志与指标上报。

---

## 34. 验收标准（UAT / Release Gates）

### 34.1 基础可用性验收

以下条件全部满足，方可认定 v1 可用：

1. 能稳定 ingest PDF 文档。
2. 能生成结构合法的 DocIR。
3. 能生成 source page 与至少两类知识页。
4. 能通过 patch 更新 wiki。
5. 能为关键 claim 生成 evidence anchor。
6. 能运行 lint 与 harness。
7. 能展示 review queue。
8. 能对失败场景生成 failure page 或 failure report。

### 34.2 质量验收（建议初始阈值）

以下阈值作为 v1 初始建议门槛，可根据领域调整：

- citation coverage >= 95%
- unsupported claim rate <= 2%
- broken wikilink count = 0（P0）
- schema violation count = 0（P0）
- re-ingest diff stability >= 90%
- duplicate entity rate <= 3%
- stale anchor rate <= 2%

### 34.3 发布门禁

以下情况不得 auto merge：

- P0 lint 存在
- harness 未运行
- regression 超阈值
- unsupported claim 增长
- 高 blast radius 未审阅
- parser fallback 且置信度不足

---

## 35. 实施路线图

### Phase 0：Specification First
目标：

- 完成 schema
- 完成 page templates
- 完成 skill contracts
- 完成 thresholds 与 review policy

交付物：

- `doc.schema.json`
- `page.schema.yaml`
- `patch.schema.json`
- `AGENTS.md`
- `OPS.md`

### Phase 1：Single Domain MVP
目标：

- 支持 PDF
- 接 2 个 parser backend
- 建立 DocIR
- 支持 source/entity/concept 三类页面
- 跑基本 harness

交付物：

- ingest pipeline
- wiki compiler
- lint + report
- golden set v1

### Phase 2：Review & Regression
目标：

- 上线 review console
- 支持 parser compare
- 支持 regression report
- 建立 failure library

### Phase 3：Knowledge Ops
目标：

- 增强 dedup、冲突管理、决策页
- 支持更多 page types
- 支持复杂多来源知识更新

### Phase 4：Scale & Platformization
目标：

- 批量 ingest
- 多项目配置
- 更成熟的 API / automation / scheduling

---

## 36. 主要风险与反模式

### 36.1 风险

1. 过早把 parser 输出 flatten 为 Markdown，导致信息不可恢复。
2. 过度依赖单 parser，导致复杂场景脆弱。
3. 让 LLM 直接覆盖 wiki，造成知识漂移。
4. 缺乏 evidence anchor，导致“看起来合理但无法审计”。
5. 没有 golden set 与 regression，导致系统越改越差。
6. 只做漂亮总结，不做结构化 claim / entity / conflict 管理。
7. 只做 Obsidian 视图，不做可视化审阅台。

### 36.2 必须避免的反模式

- 一个 super prompt 统治全流程
- 把 schema 写成纯口头说明
- 解析失败后静默 fallback 且不告知
- 直接 merge 大范围改动
- 没有 parser 版本记录
- 没有 patch 与回滚机制
- 没有 failure page 沉淀

---

## 37. 建议的 v1 默认技术策略

以下策略为推荐默认值，不是强制实现形式，但应满足其能力要求。

### 37.1 Parser 策略
- 采用 router + ensemble 思路
- 轻量 route 用快速文本/结构 parser
- 复杂 route 用高保真 PDF parser
- 复杂表格与公式场景允许引入专门修复步骤

### 37.2 知识策略
- claim-first，而非 summary-first
- source page 优先落地，再扩展 entity/concept page
- 失败模式作为一等知识对象

### 37.3 发布策略
- 默认保守 auto merge
- 高价值结论必须审阅后批准
- patch small and safe

---

## 38. 示例 Schema

### 38.1 DocIR 片段示例

```json
{
  "doc_id": "doc.readoc.2025",
  "source_id": "src_0001",
  "parser": "complex_pdf_route.primary",
  "parser_version": "1.2.0",
  "schema_version": "3",
  "page_count": 2,
  "pages": [
    {
      "page_no": 1,
      "width": 2480,
      "height": 3508,
      "rotation": 0,
      "ocr_used": false,
      "blocks": ["p1_b1", "p1_b2", "p1_b3"]
    }
  ],
  "blocks": [
    {
      "block_id": "p1_b1",
      "page_no": 1,
      "block_type": "title",
      "reading_order": 1,
      "bbox": [120, 180, 2140, 340],
      "parent_id": null,
      "children_ids": [],
      "text_plain": "READOC: A Benchmark for End-to-End Document Structure Extraction",
      "text_md": "READOC: A Benchmark for End-to-End Document Structure Extraction",
      "confidence": 0.99,
      "source_parser": "parser_a",
      "source_node_id": "node_001"
    }
  ],
  "relations": [],
  "warnings": []
}
```

### 38.2 Wiki Frontmatter 示例

```yaml
id: concept.reading_order
type: concept
title: Reading Order
status: auto
schema_version: "3"
created_at: 2026-04-13
updated_at: 2026-04-13
source_docs:
  - src_0001
related_entities:
  - parser.docir_router
related_claims:
  - claim_001
review_status: pending
```

### 38.3 Claim 示例

```json
{
  "claim_id": "claim_001",
  "statement": "多页端到端文档结构抽取需要同时兼顾全局结构与局部保真。",
  "subject_entity_id": "concept.end_to_end_dse",
  "predicate": "requires_balancing",
  "object": "global_structure_and_local_fidelity",
  "status": "supported",
  "confidence": 0.94,
  "page_refs": [1, 2],
  "evidence_anchors": ["anchor_001", "anchor_002"],
  "supporting_sources": ["src_0001"],
  "conflicting_sources": [],
  "inference_note": null,
  "updated_at": "2026-04-13T00:00:00Z"
}
```

### 38.4 Patch 示例

```json
{
  "patch_id": "patch_20260413_001",
  "run_id": "run_20260413_001",
  "source_id": "src_0001",
  "generated_at": "2026-04-13T10:00:00Z",
  "changes": [
    {
      "type": "create_page",
      "target": "wiki/sources/src_0001.md"
    },
    {
      "type": "update_page",
      "target": "wiki/concepts/reading-order.md"
    }
  ],
  "blast_radius": {
    "pages": 2,
    "claims": 4,
    "links": 7
  },
  "risk_score": 0.31,
  "review_required": false,
  "merge_status": "pending"
}
```

---

## 39. 建议的 AGENTS / OPS 约束

### 39.1 AGENTS 约束

系统级 agent 或 skill 使用说明至少应包含：

- system goal
- allowed inputs
- required outputs
- forbidden actions
- citation/evidence policy
- escalation policy
- review triggers

### 39.2 OPS 约束

运行规范至少应包含：

- source onboarding 流程
- parser failure 处理流程
- review SLA
- schema upgrade 流程
- regression 发布流程
- rollback 流程

---

## 40. 结论

本项目的目标不是复制一个“更花哨的 Karpathy LLM Wiki”，而是将其模式升级为一套 **专业级、证据驱动、schema-first、patch-based、harness-gated 的 Document Parsing Wiki 系统**。

该系统应满足以下本质要求：

1. **解析与知识维护解耦，但通过 DocIR 连接**
2. **Markdown 作为优秀视图层保留，但不承担机器真相职责**
3. **LLM 参与整理知识，但不能绕开 evidence、patch 与 review**
4. **Harness 成为执行质量与发布质量的核心门禁**
5. **失败模式、冲突知识、解析局限都应被系统性沉淀**

如果本需求文档被完整执行，最终产物将不是一个简单的“LLM 写 wiki”系统，而是一个可长期演进的 **Document Parsing Knowledge OS**。

---

## 41. 后续建议（实施优先顺序）

建议按以下顺序进入落地：

1. 先冻结 `DocIR Schema`
2. 再冻结 8 个 Skills Contract
3. 再实现 PDF-only MVP
4. 再建立 Golden Set 与 Harness
5. 再建设 Review Console
6. 最后扩展更多 parser、格式与自动化能力

---

## 42. 参考灵感来源（非规范部分）

以下方向为本系统设计的主要灵感来源：

- Karpathy 的 LLM Wiki 模式
- Markdown-first 的知识维护工作流
- 文档解析领域对 layout / reading order / table / formula 的专业要求
- 以中间表示（IR）承接多 parser 输出的工程实践
- 以 harness / regression / review gate 保证长期质量的工程思想
