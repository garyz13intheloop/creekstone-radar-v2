# Creekstone Radar v2

Creekstone Radar v2 是一个由投资论文 (Investment Thesis) 驱动的自动化产品情报与投研系统。它通过多源信号采集、三阶段过滤评分、以及闭环的机器学习自进化机制，从海量噪声中精准捕捉具备 Alpha 潜力的 AI 与 Agent 产品。

## 1. 核心架构设计

系统设计为三个轨道，分别对应不同的投资逻辑：
- **Track A (Agent 框架)**: 基础设施、开发工具、MCP 生态。关注采用速度与技术壁垒。
- **Track B (垂直 Agent / FDE化)**: 全领域专家 (Full Domain Expert)。关注业务闭环、专有数据霸权、及替换专家的能力。
- **Track C (Agent to Agent 网络)**: 智能体间通信协议、发现机制、软硬结合执行网络。

## 2. 数据来源矩阵 (5大维度)
- **平台源**: ProductHunt, GitHub (Trending + Events Spike), arXiv
- **社区源**: Hacker News, Reddit, Discord (Passive listeners)
- **X (Twitter)**: 基于 OAuth 1.0a 的定向关键词搜索 + 大 V 监测
- **流量源**: Similarweb (通过 Scrape.do 周度扫描，监控爆发性增长)
- **榜单源**: OpenRouter Apps Rankings (实时 Token 使用量)

## 3. 三层漏斗与自进化机制

1. **S1 硬规则过滤**: 毫秒级剔除噪音（过滤垃圾分类、低互动产品、非代理类项目）。
2. **S2 Track 分类路由**: 通过 LLM 快速判断赛道与相关性，将上下文注入评分模型。
3. **S3 核心评分**: 基于 5 维度投资哲学 (AI Native, Niche 壁垒, 商业模式逻辑, 团队进化力, 加减分项) 进行深入量化评估。

**自进化闭环**: 你的每一次“点赞/感兴趣”点击，会被存入 `feedback.jsonl`，系统会自动将这些反馈（Few-shot samples）注入下一次评分中，实现系统对你个人品味的实时对齐。

## 4. 获取简报与协作

- **每日推送**: 通过飞书机器人（Feishu Webhook）推送每日 Top 5 信号与异常预警。
- **网页仪表盘**: 使用 Streamlit 搭建的投研工作台，支持跨源 dedup、评分细项回溯、流量增长曲线及创始人背景追踪。

## 5. 项目说明
- **目录结构**:
  - `collectors/`: 不同源的数据抓取逻辑。
  - `enrichers/`: LLM 摘要、关键词提取与评分计算。
  - `pipeline/`: 核心调度逻辑 (Runner)。
  - `storage/`: NDJSON 格式的结构化数据存储。
  - `reports/`: 飞书日报与周报生成逻辑。
  - `webapp/`: 交互式仪表盘网页。

## 6. 使用建议
- 每日检查飞书简报，点击按钮打标（感兴趣/忽略）。
- 网页端 Dashboard 展示了所有信号的详细数据，是穿透式投研的主要阵地。
- 若需自定义规则（S1 过滤或 S3 权重），请直接修改 `config.py` 或 `pipeline/s3_scorer.py` 后提交仓库。

---

*Creekstone Ventures — Powered by Agentic Intelligence.*
