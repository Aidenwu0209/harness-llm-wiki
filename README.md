# DocOS - Document Parsing Knowledge OS

一套证据优先型文档解析知识操作系统。将异构文档编译为可验证、可追溯、可维护的结构化知识库。

```text
Raw Sources → Parser Router → Canonical DocIR → Claim/Entity Graph → Markdown Wiki → Review & Harness
```

## 核心理念

| 原则 | 说明 |
|------|------|
| Raw Source 不可变 | 原始文档是最终真相，任何流程不可覆盖 |
| DocIR 是机器真相 | Canonical DocIR 承载全部结构、布局、证据信息 |
| Markdown 是视图层 | 面向人类浏览与 LLM 协作，不是唯一机器真相 |
| 证据锚点 | 每条关键 claim 必须链接回源文档页/块位置 |
| Patch 模式 | LLM 只生成变更提案，经 lint → review → merge 后才写入正式库 |
| Harness 门禁 | 未通过质量评估的结果不得自动合并 |
| 人机协同 | 高风险、低置信度、跨页复杂结构进入 review queue |

## 技术栈

- **语言**: Python 3.12+
- **Schema**: Pydantic v2（所有模型强制类型校验）
- **类型检查**: mypy --strict
- **CLI**: Click
- **配置**: YAML（外部化，不硬编码到 prompt）
- **Wiki 输出**: Markdown + YAML Frontmatter（兼容 Obsidian）

## 项目结构

```text
docos/                        # 核心包
  models/                     # 数据模型
    docir.py                  #   Canonical DocIR (19 block types, 10 relation types)
    patch.py                  #   变更提案 (11 change types, 5 merge statuses)
    page.py                   #   Wiki 页面模板 (8 page types)
    knowledge.py              #   Entity / Claim / Relation / Evidence Anchor
    source.py                 #   Source Registry Record
    config.py                 #   外置配置 (Router / Threshold / Gate / Policy)
  pipeline/                   # 解析管线
    parser.py                 #   Parser Backend 抽象接口
    router.py                 #   信号驱动的路由选择
    orchestrator.py           #   Fallback 执行编排
    normalizer.py             #   Page-local 归一化 + Document-global Repair
  knowledge/                  # 知识工程
    extractor.py              #   Entity / Claim / Relation 抽取 Pipeline
    ops.py                    #   Conflict / Dedup / Deprecation 工作流
  wiki/                       # Wiki 编译
    compiler.py               #   8 种页面类型的 Markdown 编译器
  lint/                       # 质量检查
    checker.py                #   结构 / 知识 / 运维 Lint (P0-P3)
  harness/                    # 评测体系
    runner.py                 #   Parse / Knowledge / Maintenance 质量评估
  review/                     # 审阅管理
    queue.py                  #   Review Queue + Approve / Reject / Request Changes
  cli/                        # 命令行接口
    main.py                   #   ingest / route / parse / compile / lint / eval / review
  registry.py                 # Source Registry (hash 去重 + ingest 历史)
  source_store.py             # 不可变 Raw Source 存储
  debug_store.py              # Debug Asset 持久化

configs/
  router.yaml                 # 路由 / 阈值 / 门禁 / 审阅策略配置

schemas/                      # JSON Schema 文件
tests/                        # 202 个单元测试
```

## 数据分层

系统明确四层真相，任一层不得假装自己是唯一真相：

```
┌─────────────────────────────────────────┐
│  Wiki View Truth    (Markdown/Obsidian)  │  人类浏览层
├─────────────────────────────────────────┤
│  Knowledge Truth   (Entity/Claim/Rel)   │  知识维护层
├─────────────────────────────────────────┤
│  DocIR Truth        (Canonical DocIR)    │  机器处理层
├─────────────────────────────────────────┤
│  Raw Source Truth   (原始文档)            │  最终证据层
└─────────────────────────────────────────┘
```

## 管线流程

```text
1. Ingest    → 注册 source，hash 去重，存入不可变 raw storage
2. Route     → 基于文档信号选择解析路由（5 条预置路由）
3. Parse     → 执行 primary parser，失败自动 fallback
4. Normalize → Page-local 归一化 + Document-global 跨页修复
5. Extract   → 抽取 Entity / Claim / Relation + Evidence Anchor
6. Compile   → 编译 Source / Entity / Concept / Failure 等 wiki 页面
7. Patch      → 生成结构化变更提案（含 risk score + blast radius）
8. Lint       → 结构 / 知识 / 运维三级检查 (P0-P3)
9. Harness    → Parse / Knowledge / Maintenance 质量评估
10. Gate      → Release Gate 决定 auto_merge 或 review_required
11. Review    → 高风险项进入 Review Queue，人工 approve/reject
```

## 快速开始

```bash
# 安装
pip install -e ".[dev]"

# 验证
python -m mypy docos/          # 类型检查
python -m pytest tests/ -v     # 运行 202 个测试

# CLI 使用
docos ingest document.pdf      # 导入文档
docos route src_xxxx           # 查看路由决策
docos lint                     # 运行 lint 检查
docos eval                     # 运行 harness 评估
docos review list              # 查看待审阅项
```

## 质量指标（v1 目标）

| 指标 | 目标 |
|------|------|
| Citation Coverage | >= 95% |
| Unsupported Claim Rate | <= 2% |
| Broken Wikilink Count | 0 |
| Schema Violation Count | 0 |
| Re-ingest Diff Stability | >= 90% |
| Duplicate Entity Rate | <= 3% |

## 设计决策

**为什么不直接让 LLM 写 Markdown？**
因为文档解析不是纯文本问题——版面、结构、证据、引用、表格、公式、阅读顺序的综合信息在 Markdown flatten 过程中会不可逆地丢失。

**为什么需要 DocIR？**
多 parser 输出需要一个统一的中间表示层。DocIR 保留了几何信息（bbox）、阅读顺序、跨页关系等 Markdown 无法承载的结构，同时支持向多种视图导出。

**为什么是 Patch 模式？**
LLM 生成的知识可能包含幻觉。通过 `generate patch → lint → review → merge` 流程，所有变更都可审计、可回滚，高风险变更必须经过人工审阅。

## 许可证

MIT
