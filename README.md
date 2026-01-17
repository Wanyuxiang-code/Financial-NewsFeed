# NewsFeed - 股票新闻 AI 分析平台

一个生产级的股票新闻 AI 分析平台，每天自动采集关注股票的新闻和 SEC 公告，通过 AI 进行智能摘要和影响评估，生成精美的每日研报。

## ✨ 功能特性

### 📰 多数据源采集
- **Finnhub**: 财经媒体新闻（中可信度）
- **SEC EDGAR**: 官方监管文件（高可信度）

### 🤖 智能 AI 分析
- **单条新闻分析**: 事件类型、影响方向、置信度等
- **股票汇总分析**: 每日整体情绪、关键事件、行动建议
- **多 Provider 支持**: Gemini / OpenAI / Claude 可切换

### 📊 研报输出
- **Markdown 研报**: 精美排版，包含情绪仪表盘、重点新闻、分股票分析
- **K 线图**: 自动生成 30 天价格走势图
- **Notion Database**: 知识库沉淀（可选）

### 🔧 生产级架构
- 三段式去重（URL规范化 → 精确Hash → 相似度）
- 统一限流 + 指数退避重试
- 完整数据追溯链路（run_id 追踪）

## 🚀 快速开始

### 1. 配置环境

```bash
cd backend
cp env_template .env
# 编辑 .env 填入你的 API keys
```

**必需的 API Keys:**
| Key | 用途 | 获取方式 |
|-----|------|----------|
| `FINNHUB_API_KEY` | 新闻数据 | [finnhub.io](https://finnhub.io) 免费注册 |
| `GEMINI_API_KEY` | AI 分析 | [Google AI Studio](https://aistudio.google.com) |
| `SEC_USER_AGENT` | SEC 公告 | 格式: `YourApp/1.0 (your@email.com)` |

### 2. 安装依赖

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows:
.\venv\Scripts\Activate.ps1
# Linux/Mac:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置关注列表

编辑 `backend/data/watchlist.yaml`:

```yaml
watchlist:
  - ticker: NVDA
    company_name: NVIDIA Corporation
    thesis: AI 算力基础设施龙头，受益于数据中心和AI训练需求
    risk_tags:
      - 估值过高
      - 出口限制
    priority: 1
    sector: AI基础设施
    keywords:
      - GPU
      - H100
      - Blackwell
```

### 4. 运行 Pipeline

```bash
cd backend

# 运行完整流水线（过去24小时的新闻）
python -m app.cli

# 指定时间范围
python -m app.cli --hours 48

# 限制每只股票分析的新闻数量（加快速度）
python -m app.cli --limit 5

# 只处理特定股票
python -m app.cli --tickers NVDA,GOOGL,TSM

# 调试模式
python -m app.cli --debug
```

### 5. 查看生成的研报

研报保存在 `backend/data/digests/` 目录:
- `digest_2026-01-17_0621.md` - Markdown 研报
- `charts/NVDA_30d_20260117.png` - K 线图

## 📅 自动化定时运行

### Windows 定时任务（本地运行）

```powershell
# 以管理员身份打开 PowerShell，运行:
cd "C:\Users\wyx\Desktop\Project\NewsFeed"
.\scripts\setup_scheduled_task.ps1 -TriggerTime "17:30"
```

**管理命令:**
```powershell
# 立即运行
Start-ScheduledTask -TaskName 'NewsFeed-DailyDigest'

# 查看任务
Get-ScheduledTask -TaskName 'NewsFeed-DailyDigest'

# 删除任务
.\scripts\setup_scheduled_task.ps1 -Remove
```

### GitHub Actions（云端运行）

如果你将项目推送到 GitHub，可以使用 GitHub Actions 自动运行：

1. 在 GitHub 仓库设置 Secrets:
   - `FINNHUB_API_KEY`
   - `GEMINI_API_KEY`
   - `SEC_USER_AGENT`

2. 工作流配置在 `.github/workflows/daily_digest.yml`
3. 默认每个工作日 22:20 UTC 自动运行

## 🖥️ API 服务器（可选）

项目包含一个 REST API 服务器，可以通过 Web 接口管理：

```bash
cd backend
uvicorn app.main:app --reload
```

访问 http://localhost:8000/docs 查看交互式 API 文档。

**API 端点:**
| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/watchlist` | 获取关注列表 |
| POST | `/api/watchlist` | 添加股票 |
| PUT | `/api/watchlist/{ticker}` | 更新股票信息 |
| DELETE | `/api/watchlist/{ticker}` | 删除股票 |
| GET | `/api/news` | 查询历史新闻 |
| POST | `/api/jobs/run` | 手动触发 Pipeline |
| GET | `/api/jobs/{run_id}` | 查看运行状态 |

## 🐳 Docker 部署（可选）

如果你想在服务器上长期运行：

```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker-compose logs -f backend
```

## 📁 项目结构

```
NewsFeed/
├── backend/
│   ├── app/
│   │   ├── api/              # REST API 路由
│   │   ├── collectors/       # 数据采集器 (Finnhub, SEC)
│   │   ├── providers/        # AI Provider (Gemini, OpenAI)
│   │   ├── outputs/          # 输出处理器 (Markdown, Notion)
│   │   ├── models/           # 数据模型 & Schemas
│   │   ├── core/             # 核心业务逻辑 (Pipeline)
│   │   └── utils/            # 工具函数 (去重, 限流, 图表)
│   ├── data/
│   │   ├── digests/          # 生成的研报
│   │   │   └── charts/       # K线图
│   │   ├── prompts/          # AI Prompt 模板
│   │   └── watchlist.yaml    # 关注股票列表
│   └── tests/                # 测试
├── scripts/
│   ├── run_digest.ps1        # 运行脚本
│   └── setup_scheduled_task.ps1  # 定时任务设置
├── .github/workflows/        # GitHub Actions
└── docker-compose.yml
```

## ⚙️ 配置选项

### 切换 AI Provider

在 `.env` 中设置:

```bash
# 使用 Gemini（推荐，有免费额度）
AI_PROVIDER=gemini
GEMINI_API_KEY=your_key
GEMINI_MODEL=gemini-2.0-flash

# 或使用 OpenAI
AI_PROVIDER=openai
OPENAI_API_KEY=your_key
OPENAI_MODEL=gpt-4o-mini
```

### 使用 Gemini 代理

如果直连 Gemini API 有问题，可以配置代理：

```bash
GEMINI_API_ENDPOINT=http://127.0.0.1:8045
```

### 输出配置

```bash
# 输出到 Markdown（默认）
OUTPUTS=markdown

# 输出到 Notion
OUTPUTS=notion
NOTION_TOKEN=your_token
NOTION_DATABASE_ID=your_database_id

# 多输出
OUTPUTS=markdown,notion
```

## 💰 成本估算

| 项目 | 成本 |
|------|------|
| Finnhub | $0（免费版，60次/分钟） |
| SEC EDGAR | $0 |
| Gemini | ~$0-3/月（免费额度充足） |
| GitHub Actions | $0（免费额度内） |

## 📝 自定义 Prompt

AI 分析的 Prompt 模板在 `backend/data/prompts/` 目录：
- `news_analysis_v1.0.txt` - 单条新闻分析
- `ticker_summary_v1.0.txt` - 股票汇总分析

可以根据需要修改这些模板来调整 AI 输出格式。

## 🔄 添加新股票

1. 编辑 `backend/data/watchlist.yaml`
2. 添加新的股票配置
3. 下次运行时自动生效

## License

MIT
