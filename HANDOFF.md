# Creekstone Sourcing Agent — 交接文档

> 生成时间：2026-05-13  
> 上下文：Gary 要求将 Hermes 模型从 z-ai/glm-5.1 切换到 anthropic/claude-opus-4.7 后继续改造工作  
> 目标：基于 creekstone-radar-v2 + creekstone-daily-feeds 两个仓库，构建一个统一的 sourcing agent

---

## 一、两个仓库现状

### 1. creekstone-radar-v2

**路径**：`~/creekstone-radar-v2`

**定位**：投资论文驱动的自动化产品情报系统，3层漏斗从噪声中捕捉Alpha

**核心架构**：Collect → S1硬规则过滤 → S2 Track路由(LLM) → S3量化评分(LLM) → Store → Feishu Push

**10个Collectors**（`collectors/`目录）：

| Collector | 文件 | API/方式 | 需要 Credentials |
|---|---|---|---|
| ProductHunt | producthunt.py | GraphQL API | PH_TOKEN ✓ |
| GitHub Trending | github_trending.py | 爬HTML(BeautifulSoup) | 无(有GITHUB_TOKEN更佳) |
| GitHub Events Spike | github_events.py | GitHub Events API | GITHUB_TOKEN |
| arXiv | arxiv_papers.py | arXiv API (XML) | 无 |
| Hacker News | hackernews.py | Algolia HN Search API | 无 |
| Discord | discord_monitor.py | Bot监听 | DISCORD_BOT_TOKEN |
| Reddit | reddit.py | Reddit API | REDDIT_CLIENT_ID/SECRET |
| X/Twitter | x_twitter.py | OAuth 1.0a Search | 4个X凭证 ✓ |
| OpenRouter Apps | openrouter_apps.py | Jina Reader抓OR排名 | 无 |
| HuggingFace | huggingface.py | HF Hub API | 无 |

**三層漏斗**：

- **S1**（`pipeline/s1_filter.py`）：零LLM成本
  - 关键词blocklist（crypto/nft/政治/体育agent等）
  - AI/Agent信号allowlist（agent/mcp/tool-use/copilot等45个词）
  - 每源阈值（PH votes≥10, GH stars_today≥20, HN points≥10, X likes≥20等）
  - Fast-pass机制（视频/trending/WoW≥200%跳过阈值）
  
- **S2**（`pipeline/s2_router.py`）：单次LLM调用/item
  - 分类到Track A(框架)/B(垂直FDE)/C(A2A网络)
  - 输出：relevant/track/confidence/fde_stage
  - Track B额外算FDE阶段：single_tool→accumulating→flywheel→achieved

- **S3**（`pipeline/s3_scorer.py`）：深度LLM评分/item
  - 5维度100分制：AI Native(0-30) + Niche壁垒(0-25) + 商业模式(0-20) + 团队(0-15) + 加减分(±10)
  - Track-aware：每Track有基准参照（Harvey $8B score≈91, LangChain≈72等）
  - FDE指数(Track B专用0-10)
  - Few-shot注入：从feedback.jsonl加载Gary的历史反馈

**LLM配置**（`config.py`）：
- 全部走OpenRouter（`https://openrouter.ai/api/v1`）
- S2/S3默认模型：`google/gemini-2.0-flash-001`
- S3 scorer.py里有硬编码fallback：`anthropic/claude-haiku-4`

**自进化3层**（`enrichers/self_evolution.py`）：
- L1: Few-shot注入（实时，从feedback.jsonl读Gary的感兴趣/忽略反馈）
- L2: Blocklist动态调整（周度，检测连续忽略模式）
- L3: 评分prompt蒸馏（月度，生成scoring_notes.md需Gary确认）

**数据模型**（`models/item.py`）：
- `SignalItem` dataclass：id/source/title/url/description/track/fde_index/score_breakdown/team/traffic/feedback_state/wow_growth/keywords/metrics...
- `ScoreBreakdown`：ai_native/niche/business/team/bonus/penalty/total/reason/plus/minus
- `TeamInfo`：founders/company_size/founded_year/location/linkedin_urls/is_chinese_heritage
- `TrafficData`：domain/total_visits/mom_growth_pct/traffic_spike/is_new_product
- ID生成：sha1(source::url)[:16]

**存储**（`storage/store.py`）：
- 按天NDJSON：`data/structured/YYYY-MM-DD.ndjson`（追加写，按ID去重）
- 周度snapshot：`data/snapshots/{source}_{date}.json`（用于WoW对比，OR+HF）
- 跨源domain级去重：在runner.py里做，优先保留PH/GH来源的canonical URL

**Webapp**（`webapp/app.py`，Streamlit）：
- 4-tab卡片：概览 / 评分详情(5维度进度条+加减分) / 团队信息 / 流量数据(Similarweb)
- 侧边栏：N天/Track/来源/评分/FDE/Watchlist/Trending筛选 + 排序
- 反馈按钮：❤️感兴趣 / 📌Watchlist / 🚫忽略 + ✏️评分覆盖
- 头部5个metric卡片

**缺失/问题**：
- `reports/` 目录不存在（README提到`reports/feishu_daily.py`但文件缺失，runner.py有import）
- 没有 GitHub Actions workflow（完全手动运行）
- Discord/Reddit collector有代码但.env里没配credentials
- LLM_TIMEOUT=60秒，对Opus级别模型可能不够

**已有数据**：
- `data/snapshots/` 有12个OpenRouter周度snapshot（4/30-5/12）
- `data/feedback/` 目录存在但未见jsonl文件
- `data/evolution/` 目录存在

---

### 2. creekstone-daily-feeds

**路径**：`~/creekstone-daily-feeds`

**定位**：四源自动抓取+AI评分+结构化存储+Streamlit浏览（V1系统，已稳定运行）

**4个Sources**（`scripts/`目录）：

| Source | 脚本 | 输出 |
|---|---|---|
| ProductHunt | product_hunt_list_to_md.py | data/producthunt/*.md |
| arXiv | arxiv_papers_to_md.py | data/arxiv/*.md |
| GitHub Trending | github_trending_to_md.py | data/github/*.md |
| ClawHub | clawhub_skills_to_md.py | data/clawhub/*.md |

**评分体系**（`common/scoring.py`）：
- 同样5维度100分制（ai_native/tech_niche/business/team/bonus/penalty）
- 但用OpenAI原生SDK + fallback链：gpt-5.2 → gpt-5.1 → gpt-4o-mini
- 输出reason_struct（summary + plus[] + minus[]）
- 通过`common/openai_fallback.py`的`chat_completion_content()`调用

**OpenAI Fallback链**（`common/openai_fallback.py`）：
- 支持3级模型候选：OPENAI_MODEL → ALTERNATE_1 → ALTERNATE_2
- 推理模型自动调整max_tokens（GLM-5/Kimi-K2/MiniMax-M2/o系列/DeepSeek-R）
- GPT-5系列自动加`reasoning_effort=low`
- 推理模型不设`response_format=json_object`（靠prompt指令）
- 5次重试+指数退避+硬超时(SIGALRM)

**存储**（`common/storage.py`）：
- 全局NDJSON：`data/structured/items.ndjson`（ID去重+source/date替换）
- 按日Parquet：`data/structured/YYYY-MM-DD.parquet`（pandas+pyarrow）
- 双写：同时写NDJSON和Parquet

**周报生成器**（`common/weekly_research.py`，1740行核心文件）：
- 数据加载：Parquet → 去重 → build_event_frame
- 关键词标准化：TERM_CANONICAL_MAP（llms→llm, agents→agent等）+ blacklist
- 文本blob构建：title + summary + keywords + tags + raw上下文
- Embedding聚类：OpenAI embedding → PCA降维 → KMeans聚类 + silhouette选K
- 信号分层：趋势变化(z-score突破) / 热度延续(EMA高位) / 新兴信号(新出现词)
- LLM生成周报主题：每个聚类→LLM生成中文标题+摘要+代表性项目
- 自动QA验证：检查themes非空、qa_pass标记

**GitHub Actions Workflows**：

1. `fetch_all_sources.yml`：
   - 每日 UTC 09:10（北京时间17:10）
   - 4源顺序执行（PH→arXiv→GH→ClawHub）
   - 智能pre-check：arXiv周末跳过、同日期不重复
   - Post-check：验证parquet完整+评分非零
   - Push用PAT，3次重试+fetch-rebase防冲突

2. `weekly_research_report.yml`：
   - 每周一 UTC 01:00（SGT 09:00）
   - 支持--depth(light/standard/deep) + --force + --week-start
   - 3次重试（429 rate limit容忍）
   - 输出验证：latest.json + latest.md + themes非空 + qa_pass

**Streamlit**（`webapp/streamlit_app.py`）：
- 日期切换 / 来源筛选 / 关键词搜索 / 项目卡片(评分+关键词+图片)
- 管理模式：编辑关键词/删除项目（需ADMIN_PASSWORD）
- 专栏功能：OpenClaw/Clawdbot + Claude Code 自动聚合
- URL参数：`?column=openclaw|claudecode`

**已有数据**：
- `data/producthunt/`：多日PH Markdown
- `data/arxiv/`：多日arXiv Markdown
- `data/structured/`：NDJSON + 按日Parquet
- `data/insights/weekly/`：周报JSON+MD（2026-W08到W14）

---

## 二、两系统对比

| 维度 | radar-v2 | daily-feeds |
|---|---|---|
| Sources | 10源（PH/GH×2/arXiv/HN/Discord/Reddit/X/OR/HF） | 4源（PH/arXiv/GH/ClawHub） |
| 过漏斗 | 3层(S1硬规则→S2 Track路由→S3评分) | 单层评分 |
| 投资分类 | Track A/B/C + FDE指数 + benchmark参照 | 无 |
| 评分prompt | Track-aware, 含参照锚点(Harvey $8B≈91等) | 通用prompt, 含详细锚点描述 |
| 自进化 | 3层(few-shot/blocklist调整/prompt蒸馏) | 无 |
| Cross-source dedup | domain级去重+source合并+优先级 | 无 |
| 趋势追踪 | WoW/MoM增长+Similarweb流量+snapshot对比 | 周报主题聚类(z-score+EMA) |
| 存储 | 按天NDJSON+周snapshot | 全局NDJSON+按日Parquet |
| CI/CD | 无 | 完善的GitHub Actions(每日+每周) |
| 周报 | 无 | 1740行完整周报生成器 |
| 飞书推送 | 代码引用但文件缺失 | 无 |
| Web UI | 4-tab卡片+反馈+评分覆盖 | 日期浏览+管理+专栏 |
| LLM调用方式 | raw requests → OpenRouter API | OpenAI SDK + 3级fallback |
| 华人创始人 | TeamInfo.is_chinese_heritage字段 | 无 |

---

## 三、Sourcing Agent 改造方向

Gary的目标：基于这两个仓库构建一个统一的 sourcing agent。以下是讨论过的方向：

### 核心决策：以 radar-v2 为骨架

理由：radar-v2 的3层漏斗+Track分类+FDE+自进化是投资论文的正确抽象，daily-feeds 没有这些概念。

### 需要从 daily-feeds 移植的组件

1. **周报生成器**：weekly_research.py（1740行），含关键词标准化+embedding聚类+LLM主题生成+自动QA
2. **GitHub Actions workflows**：fetch_all_sources.yml + weekly_research_report.yml 的CI/CD框架
3. **OpenAI fallback链**：openai_fallback.py 的多模型容错机制
4. **Parquet存储**：按日Parquet比纯NDJSON更适合大数据量分析
5. **ClawHub collector**：radar-v2没有这个source

### 需要补全的 radar-v2 组件

1. **reports/feishu_daily.py**：runner.py 有 import 但文件不存在
2. **GitHub Actions**：每日自动运行 + 每周报告
3. **Discord/Reddit credentials**：有代码但没配
4. **LLM timeout**：60秒对强模型可能不够

### 新增 sourcing 能力（Hermes已有skills可复用）

1. **创始人追踪**：`founder-trace` skill（3-Pass: Identity→SocialGraph→Contact）
2. **华人创始人批量筛查**：`chinese-founder-trace` skill
3. **融资信号**：Crunchbase/IT桔子/36kr等
4. **竞品监控**：类似产品的动态追踪
5. **批量创始人研究**：`batch-founder-research` skill

### 建议优先级

(A) 补全 CI/CD（GitHub Actions + 每日自动运行）— 最基础
(B) 移植周报生成器到 radar-v2 — 高价值
(C) 补全 reports/feishu_daily.py — 日常使用
(D) 合并数据存储层（统一到 SignalItem 模型 + Parquet）— 数据基础
(E) 新增 sourcing 专用 collector（融资/创始人/竞品）— 扩展能力
(F) Webapp 整合（把 daily-feeds 的管理+专栏功能搬过来）— 体验优化

---

## 四、关键文件索引

### radar-v2 核心文件
```
config.py                          # 全局配置+credentials
models/item.py                     # SignalItem/ScoreBreakdown/TeamInfo/TrafficData
collectors/base.py                 # BaseCollector ABC
collectors/producthunt.py           # PH GraphQL
collectors/github_trending.py      # GH Trending HTML爬取
collectors/github_events.py        # GH Events Spike
collectors/arxiv_papers.py         # arXiv API
collectors/hackernews.py           # Algolia HN Search
collectors/x_twitter.py            # OAuth 1.0a X搜索
collectors/openrouter_apps.py      # Jina Reader抓OR排名
collectors/huggingface.py          # HF Hub API
collectors/discord_monitor.py      # Discord Bot
collectors/reddit.py                # Reddit API
collectors/similarweb_monitor.py   # Scrape.do流量监控(周度)
pipeline/runner.py                  # 主调度：Collect→S1→Dedup→S2→S3→Store→Feishu
pipeline/s1_filter.py              # 硬规则过滤
pipeline/s2_router.py              # Track分类路由
pipeline/s3_scorer.py              # 5维评分+few-shot
pipeline/self_cleaner.py           # 死链清理+过期归档
pipeline/migrate_old.py            # V1→V2数据迁移
enrichers/llm_enricher.py          # 旧版enricher(0-10分，已被S3替代)
enrichers/self_evolution.py        # 3层自进化引擎
storage/store.py                    # NDJSON存储+snapshot
webapp/app.py                      # Streamlit Dashboard
.env                               # credentials(已配OR/X/PH)
```

### daily-feeds 核心文件
```
common/scoring.py                   # 评分(OpenAI SDK+fallback)
common/storage.py                   # NDJSON+Parquet双写
common/openai_fallback.py           # 3级模型fallback+重试
common/weekly_research.py           # 周报生成器(1740行)
common/keyword_utils.py             # 关键词工具
scripts/product_hunt_list_to_md.py   # PH抓取
scripts/arxiv_papers_to_md.py      # arXiv抓取
scripts/github_trending_to_md.py   # GH抓取
scripts/clawhub_skills_to_md.py    # ClawHub抓取
scripts/weekly_research_report.py  # 周报CLI入口
scripts/keyword_trends.py          # 关键词趋势
scripts/generate_columns.py        # 专栏生成
.github/workflows/fetch_all_sources.yml      # 每日CI
.github/workflows/weekly_research_report.yml # 每周CI
webapp/streamlit_app.py            # Streamlit UI
webapp/weekly_report_view.py       # 周报查看页
app.py                             # Streamlit Cloud入口
.env.example                       # 环境变量模板
```

---

## 五、注意事项

1. **.env泄露**：radar-v2的.env包含明文credentials（OR API key/X OAuth/PH token），已被读到交接文档里。新模型不应在输出中暴露这些值。
2. **评分体系差异**：radar-v2的S3用Niche(0-25)，daily-feeds用tech_niche(0-25)，本质相同但字段名不同。合并时需统一。
3. **daily-feeds的weekly_research.py是1740行巨文件**，移植时需要大量阅读，建议分段读。
4. **radar-v2的runner.py引用了不存在的`reports.feishu_daily`**，运行时会ImportError。
5. **OpenRouter模型选择**：框架内LLM不需要用Opus，S2用flash级即可，S3可考虑haiku/sonnet级。成本控制重要——每日100+items × S2 + S3 = 大量调用。

---

*文档结束。新模型接手后，建议先用 `session_search` 搜 "creekstone-radar" 回忆相关上下文，然后直接从此文档开始工作。*
