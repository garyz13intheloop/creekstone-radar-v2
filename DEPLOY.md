# 部署指南

## 1. Streamlit Cloud（主 App）

### 步骤
1. 打开 https://share.streamlit.io/ 用 GitHub 登录
2. New app → 选择 `creekstone-radar-v2` 仓库
3. Branch: `main` | Main file: `app.py`
4. Advanced settings → Secrets 填入以下配置：

```toml
OPENROUTER_API_KEY = "sk-or-v1-..."
PRODUCTHUNT_DEVELOPER_TOKEN = "..."
X_API_KEY = "..."
X_API_SECRET = "..."
X_ACCESS_TOKEN = "..."
X_ACCESS_TOKEN_SECRET = "..."
FEISHU_WEBHOOK_URL = "..."
BITABLE_APP_TOKEN = "..."
BITABLE_TABLE_ID = "..."
FEISHU_APP_ID = "..."
FEISHU_APP_SECRET = "..."
LLM_MODEL = "google/gemini-2.0-flash-lite-001"
S3_MODEL = "anthropic/claude-sonnet-4-5"
ENABLED_SOURCES = "producthunt,github_trending,github_events,arxiv,hackernews,x_twitter,openrouter,huggingface"
```

5. Deploy → 获得 URL 如 `https://creekstone-radar.streamlit.app`

### 数据更新
- GitHub Actions 每天 SGT 18:00 自动运行并 commit 数据
- Streamlit Cloud 检测到新 commit 后自动重启，展示最新数据

---

## 2. Netlify（落地页 + 跳转）

### 步骤
1. 打开 https://app.netlify.com → Add new site → Import from Git
2. 选择 `creekstone-radar-v2` 仓库
3. Build settings:
   - Build command: `echo done`
   - Publish directory: `netlify`
4. Deploy

### 更新 Streamlit URL
部署完 Streamlit Cloud 后，把真实 URL 更新到 `netlify/index.html`：
```
href="https://creekstone-radar.streamlit.app"
```

---

## 3. GitHub Actions Secrets 配置

在 GitHub 仓库 Settings → Secrets and variables → Actions，添加：

| Secret | 说明 |
|--------|------|
| `OPENROUTER_API_KEY` | OpenRouter API Key |
| `PRODUCTHUNT_DEVELOPER_TOKEN` | Product Hunt API Token |
| `X_API_KEY` / `X_API_SECRET` | Twitter API OAuth |
| `X_ACCESS_TOKEN` / `X_ACCESS_TOKEN_SECRET` | Twitter Access Token |
| `FEISHU_WEBHOOK_URL` | 飞书 Webhook |
| `BITABLE_APP_TOKEN` / `BITABLE_TABLE_ID` | 飞书多维表格 |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书应用凭证 |
| `GH_PAT` | GitHub Personal Access Token (contents: write) |

每天 SGT 18:00 自动采集、评分、推送飞书、commit 数据。
