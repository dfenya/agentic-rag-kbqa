# Agentic RAG KBQA

基于 LangGraph 的 Agentic RAG知识库问答。

## 整体架构

```
┌──────────────────────────────────────────────────────┐
│  前端 (Vue 3 + Element Plus)                         │
│  ChatView / DocumentsView / MemoryView / SettingsView │
└──────────────────────┬───────────────────────────────┘
                       │ SSE / REST
┌──────────────────────▼───────────────────────────────┐
│  后端 (FastAPI)                                      │
│                                                      │
│  POST /chat/stream  ←── SSE 流式对话                  │
│  POST /documents    ←── 文档上传 + 进度推送            │
│                                                      │
│  ┌─────────────────────────────────────────────┐     │
│  │  文档摄入管线                                  │     │
│  │  SHA256 去重 → MinerU 解析 → 父子分块 → Qdrant │     │
│  └─────────────────────────────────────────────┘     │
│                                                      │
│  ┌─────────────────────────────────────────────┐     │
│  │  Agentic RAG (LangGraph)                     │     │
│  │                                              │     │
│  │  主图:                                       │     │
│  │  加载记忆 → 摘要历史 → 改写/拆解问题            │     │
│  │     → Agent 子图 (多实例并行) → 汇总回答       │     │
│  │                                              │     │
│  │  Agent 子图 (每个子问题一个实例):               │     │
│  │  orchestrator ←→ tools                       │     │
│  │       ↓                 ↑                    │     │
│  │  [反复: 决定调用哪个工具 → 执行 → 分析结果      │     │
│  │   → 信息不够就继续搜 → 够了就汇总输出]          │     │
│  └─────────────────────────────────────────────┘     │
│                                                      │
│  ┌─────────────────────────────────────────────┐     │
│  │  长期记忆                                     │     │
│  │  LLM 提取 → Qdrant 语义检索 → SQLite 元数据    │     │
│  └─────────────────────────────────────────────┘     │
└──────┬──────────────────────┬────────────────────────┘
       │                      │
┌──────▼──────┐    ┌──────────▼──────────┐
│  Qdrant     │    │  SQLite             │
│  向量检索    │    │  文档/会话/消息/记忆  │
│  混合检索    │    │  LangGraph 存档     │
└─────────────┘    └─────────────────────┘
       │
┌──────▼──────┐
│  Ollama     │
│  LLM + Emb  │
└─────────────┘

外部依赖（可选）:
  MinerU API ←── PDF 解析 (HTTP)
```

## 快速开始

### 依赖

- Python 3.12、Node 20+
- Ollama
- MinerU（可选，需 PDF 解析时启动）

### 安装

```bash
# MinerU（PDF 解析）
pip install uv -i https://mirrors.aliyun.com/pypi/simple
uv pip install -U "mineru[all]" -i https://mirrors.aliyun.com/pypi/simple

# 后端
cd backend
pip install -r requirements.txt

# 前端
cd frontend
npm install
```

### 运行

```bash
# 1. Ollama
ollama serve
ollama pull qwen3:4b-instruct-2507-q4_K_M

# 2. MinerU（需要 PDF 解析时开，端口在 config/mineru.yml 配）
mineru-api --host 127.0.0.1 --port 8085

# 3. 后端
cd backend
python run.py                    # 端口 8000

# 4. 前端
cd frontend
npm run dev                      # 端口 5173
```

## 核心功能

### 文档处理管线

```
上传 → 去重(SHA256，同 KB 内唯一) → MinerU(PDF→Markdown，支持双栏/表格)
     → 父子分块(父块 600-4000 字，子块 500 字) → Qdrant 向量化
```

Web 界面实时显示进度：去重检查 → MinerU 解析 → 文档分块 → 向量入库。中间文件保存在 `data/` 下，失败自动清理。

MinerU 是独立的 HTTP 服务，配置在 `backend/config/mineru.yml`，不启动也能上传 Markdown 文件。

### 混合检索

密集向量 (bge-large-zh-v1.5) + BM25 稀疏检索，Qdrant RRF 融合。检索命中子块后回溯完整父块，给 LLM 的上下文既有精度又有背景。

### Agentic RAG 工作流

```
用户提问 → load_long_term_memory (注入用户偏好/历史)
         → summarize_history (对话太长就压成摘要)
         → rewrite_query (LLM 分析意图，拆成子问题)
               ↓
         问题够明确？
         ├─ 不够 → request_clarification (中断，反推问题让用户确认)
         └─ 明确 → 启动多个 Agent 子图，每个处理一个子问题
                         ↓
                    orchestrator (LLM 决策)
                    "现在手上有哪些信息？还需要什么？"
                         ↓
               ┌───────┼───────┐
               ↓       ↓       ↓
            search  search  search  (调用不同检索工具)
               ↓       ↓       ↓
            "这些结果够不够回答子问题？"
            ├─ 不够 → 换关键词/策略，继续搜 (循环)
            └─ 够了 → collect_answer，输出这个子问题的答案
                         ↓
              aggregate_answers (汇总所有子答案 → 最终回答)
```

Agent 的关键行为是**自主决策**而非走固定流程：

- **工具选择**：orchestrator 根据当前信息缺口决定用哪个检索工具（child chunk 精确匹配 / parent chunk 回溯上下文 / 跨文档交叉验证）
- **迭代检索**：检索一轮可能不够，Agent 会根据中间结果调整策略继续搜，直到信息充分或达到上限
- **并行处理**：多个子问题各自独立跑 Agent 子图，互不干扰，最后汇总
- **熔断兜底**：每轮最多 N 次工具调用、最多 M 次迭代，超限自动用已有信息生成回答

### 长期记忆

每轮对话结束后 LLM 自动提取，按会话隔离：

| 类型 | 说明 |
|------|------|
| conversation_summary | 当前会话摘要，随对话更新覆盖 |
| user_preference | 用户偏好（"回答简洁""用表格呈现"等） |
| faq_pattern | 同主题被命中 3 次以上自动升级 |

存储：SQLite 存元数据 + Qdrant 存向量，检索时按 importance × recency 融合排序。

### 对话管理

- 流式输出 (SSE)
- 点击停止中止生成，后端停止 LLM 调用并持久化部分内容
- 切换会话不丢进度，后台处理完切回来能看到完整结果
- 澄清中断：问题不够明确时反推问题让用户确认

## 配置

| 位置 | 用途 |
|------|------|
| `backend/.env.dev` | 环境变量：模型、端口、chunk 参数等 |
| `backend/config/mineru.yml` | MinerU API 地址和请求参数 |
| Web 界面设置页 | LLM 模型、top-k、记忆开关等 |
| `data/settings.json` | Web 界面修改后的持久化配置 |

## 项目结构

```
backend/
  app/
    api/v1/          # REST API
      chat.py        # SSE 流式对话
      conversations.py
      documents.py   # 文档管理
      uploads.py     # 上传 + SSE 进度
      knowledge_bases.py
      memories.py
      settings.py
      system.py      # 健康检查
    core/            # 配置 (config.py)、容器 (container.py)
    domain/          # ORM 模型、Pydantic Schema、枚举
    ingestion/       # 文档摄入
      pipeline.py    # 管线编排
      dedup.py       # SHA256 去重
      extractor.py   # PDF→Markdown (调 mineru-api)
      chunker.py     # 父子分块
    rag/             # LangGraph Agent
      graph.py       # 图工厂
      graph_state.py # State 定义
      nodes.py       # 节点函数
      edges.py       # 路由
      tools.py       # 检索工具
      memory.py      # 长期记忆加载/存储
      prompts/       # 提示词
    services/        # 业务层
      chat_service.py           # 对话编排（核心）
      conversation_service.py
      document_service.py
      long_term_memory_service.py
    stores/          # 数据访问
      qdrant_store.py
      parent_store.py
      sqlite_store.py
      long_term_memory_store.py
  config/
    mineru.yml       # MinerU API 配置
  data/              # SQLite、上传文件、中间产物、settings.json
frontend/
  src/
    views/           # ChatView、DocumentsView、MemoryView、SettingsView
    components/      # 聊天组件、文档上传、侧边栏
    stores/          # Pinia (chat、documents、memory、conversations)
    composables/     # useChatStream (SSE 流式对话)
    config/          # brand.ts (品牌文案)
scripts/             # 批量导入等
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/chat/stream` | SSE 流式对话 |
| POST | `/api/v1/chat/resume` | 澄清中断后恢复 |
| GET/PATCH/DELETE | `/api/v1/conversations/{id}` | 会话 |
| GET | `/api/v1/conversations/{id}/messages` | 消息历史 |
| GET | `/api/v1/documents` | 文档列表 |
| POST | `/api/v1/documents` | 上传文档 |
| DELETE | `/api/v1/documents/{id}` | 删除文档（含向量和文件） |
| POST | `/api/v1/documents/{id}/retry` | 重试失败文档 |
| GET/POST | `/api/v1/knowledge-bases` | 知识库 |
| DELETE | `/api/v1/knowledge-bases/{id}` | 删除知识库 |
| GET/DELETE | `/api/v1/memories` | 长期记忆 |
| PATCH | `/api/v1/memories/{id}` | 更新记忆 |
| GET/PUT | `/api/v1/settings` | 系统设置 |
| GET | `/api/v1/models` | Ollama 模型列表 |
