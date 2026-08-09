# Agentic RAG 知识库

上传文档 → 自动解析分块 → 混合检索 → AI 自主推理回答。

不是简单的文档搜索，而是让 LLM 像研究员一样主动检索、分析、综合多份文档后再回答。

## 技术栈

| 层 | 技术 |
|---|---|
| LLM | Ollama + qwen3:4b（本地部署） |
| 嵌入模型 | BAAI/bge-large-zh-v1.5（密集）+ Qdrant/bm25（稀疏） |
| 向量库 | Qdrant（本地文件模式，混合检索 + RRF 融合） |
| 关系库 | SQLite（WAL 模式，存文档/会话/消息/记忆） |
| Agent | LangGraph + SqliteSaver（支持中断恢复） |
| 后端 | FastAPI + Pydantic Settings |
| 前端 | Vue 3 + Vite + Element Plus |

## 快速开始

### 1. 启动 Ollama

```bash
ollama serve
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

### 2. 启动后端

```bash
cd backend
pip install -r requirements.txt
python run.py
```

验证：访问 `http://localhost:8000/api/v1/health`，确认 sqlite、qdrant、ollama 都是 ok。

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev        # 开发模式，访问 http://localhost:5173
```

生产模式：
```bash
npm run build      # 产物在 dist/，由 FastAPI 托管静态文件
```

### 4. 导入文档

在 Web 界面上传 PDF 或 Markdown 文件，支持的格式：`.pdf` `.md`

也可以批量导入：
```bash
python scripts/seed_flk.py /path/to/pdfs/
```

## 项目结构

```
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI 入口，lifespan 管理
│   │   ├── api/v1/                 # REST API
│   │   │   ├── chat.py             # POST /chat/stream（SSE 流式）
│   │   │   ├── conversations.py    # 会话 CRUD
│   │   │   ├── documents.py        # 文档管理
│   │   │   ├── uploads.py          # 文件上传 + 进度推送
│   │   │   ├── knowledge_bases.py  # 知识库
│   │   │   ├── memories.py         # 长期记忆
│   │   │   ├── settings.py         # 系统设置
│   │   │   └── system.py           # 健康检查
│   │   ├── core/                   # 配置、DI 容器、中间件、异常
│   │   ├── domain/                 # ORM 模型、枚举、Pydantic Schema
│   │   ├── ingestion/              # 文档摄入管线
│   │   │   ├── pipeline.py         # 编排：去重 → 提取 → 分块 → 写入
│   │   │   ├── dedup.py            # SHA-256 去重
│   │   │   ├── chunker.py          # 文档结构化分块
│   │   │   └── extractor.py        # PDF → Markdown
│   │   ├── rag/                    # RAG Agent
│   │   │   ├── graph.py            # LangGraph 图工厂
│   │   │   ├── nodes.py            # 图节点（重写、摘要、orchestrator 等）
│   │   │   ├── edges.py            # 路由边
│   │   │   ├── tools.py            # 检索工具（search_child_chunks 等）
│   │   │   ├── memory.py           # 长期记忆加载与存储
│   │   │   └── prompts/legal.py    # 系统提示词
│   │   ├── services/               # 业务层
│   │   │   ├── chat_service.py     # 对话编排（核心）
│   │   │   ├── conversation_service.py
│   │   │   ├── document_service.py
│   │   │   └── long_term_memory_service.py
│   │   └── stores/                 # 存储层
│   │       ├── qdrant_store.py     # 子块混合检索
│   │       ├── parent_store.py     # 父块（纯 payload 存储）
│   │       ├── long_term_memory_store.py
│   │       └── sqlite_store.py     # 结构化数据 DAO
│   └── data/                       # SQLite 数据库、上传文件、settings.json
├── frontend/
│   ├── src/
│   │   ├── views/                  # ChatView / DocumentsView / MemoryView / SettingsView
│   │   ├── components/             # 聊天组件、文档上传、侧边栏
│   │   ├── stores/                 # Pinia 状态管理
│   │   ├── composables/            # useChatStream
│   │   └── config/brand.ts         # 品牌配置（名称、图标、文案集中管理）
│   └── package.json
└── scripts/                        # 清理工具、批量导入
```

## 核心功能

### 混合检索

密集向量（bge-large-zh-v1.5）做语义匹配，BM25 做关键词匹配，Qdrant 自动 RRF 融合排序。

### 父子分块

文档按标题层级切分后，父块保留完整上下文（600-4000 字），子块用来向量检索（500 字重叠 100）。检索命中的子块自动回溯整个父块，送到 LLM 时既有精度又有上下文。

### 多 Agent 协作

复杂问题自动拆成子问题，每个子问题独立开一个 agent 去检索、分析，最后汇总成一份连贯的回答。Agent 内部有熔断机制：搜索轮次超限自动兜底。

### 长期记忆

三种类型自动管理：
- **用户偏好**：从用户原话中提取（"用表格呈现""我是工程师"等），宁缺勿滥
- **对话摘要**：每个会话自动生成摘要，随对话推进持续更新
- **高频问题**：同主题被问 3 次以上自动标记为 FAQ

### 完全本地

所有组件（Ollama、Qdrant、SQLite）都在本地跑，数据不出机器，不需要网络。

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/chat/stream` | 流式对话（SSE） |
| POST | `/api/v1/chat/resume` | 中断后恢复 |
| GET/PATCH/DELETE | `/api/v1/conversations/{id}` | 会话管理 |
| GET | `/api/v1/conversations/{id}/messages` | 消息历史 |
| GET | `/api/v1/documents` | 文档列表 |
| POST | `/api/v1/documents` | 上传文档 |
| DELETE | `/api/v1/documents/{id}` | 删除文档 |
| POST | `/api/v1/documents/{id}/retry` | 重试失败文档 |
| POST/GET/DELETE | `/api/v1/knowledge-bases` | 知识库管理 |
| GET/PATCH/DELETE | `/api/v1/memories` | 记忆管理 |
| GET/PUT | `/api/v1/settings` | 系统设置 |
| GET | `/api/v1/models` | Ollama 模型列表 |

## 配置

环境变量在 `backend/.env.dev` 里修改，Web 界面能改的部分（模型、top-k、记忆开关等）保存后即生效，写入 `data/settings.json`。

需要改 `num_ctx` 等 Web 界面没有的配置项时，直接编辑 `.env.dev` 然后重启 `python run.py`。
