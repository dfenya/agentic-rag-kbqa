# Agentic RAG KBQA

基于 LangGraph 的 RAG 知识库问答系统，上传文档后可对话查询。

## 环境

- Python 3.12
- Node 20+
- Ollama（本地 LLM）
- MinerU（PDF 解析，可选，需要时单独启动）

## 安装

```bash
# 后端
cd backend
pip install -r requirements.txt

# 前端
cd frontend
npm install
```

## 运行

```bash
# 1. Ollama
ollama serve
ollama pull qwen3:4b-instruct-2507-q4_K_M

# 2. MinerU API（PDF 解析，可选）
mineru-api --host 127.0.0.1 --port 8085

# 3. 后端
cd backend
python run.py

# 4. 前端
cd frontend
npm run dev
```

访问 `http://localhost:5173`。

## 配置

- 环境变量：`backend/.env.dev`
- Web 界面可改：模型、top-k、记忆开关，保存到 `data/settings.json`
- 其他配置项（num_ctx 等）改 `.env.dev` 后重启后端

## 文档处理

上传 PDF/Markdown → SHA256 去重 → MinerU 转 Markdown → 父子分块 → Qdrant 向量化。

处理过程在 Web 界面有进度展示。中间文件保存在 `data/` 下。

MinerU 配置文件：`backend/config/mineru.yml`。

## 项目结构

```
backend/
  app/
    api/v1/        # REST API
    core/          # 配置、容器、中间件
    domain/        # ORM、Schema
    ingestion/     # 文档摄入：去重、提取、分块
    rag/           # LangGraph Agent：节点、边、工具、提示词
    services/      # 业务层
    stores/        # 存储层
  config/          # MinerU 等外部服务配置
  data/            # SQLite、上传文件、中间产物
frontend/
  src/
    views/         # 页面
    components/    # 组件
    stores/        # Pinia
    composables/   # useChatStream
scripts/           # 批量导入等工具
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/chat/stream` | SSE 流式对话 |
| POST | `/api/v1/chat/resume` | 中断恢复 |
| GET/PATCH/DELETE | `/api/v1/conversations/{id}` | 会话 |
| GET | `/api/v1/conversations/{id}/messages` | 消息历史 |
| GET/POST/DELETE | `/api/v1/documents` | 文档 |
| POST | `/api/v1/documents/{id}/retry` | 重试失败文档 |
| CRUD | `/api/v1/knowledge-bases` | 知识库 |
| GET/PATCH/DELETE | `/api/v1/memories` | 长期记忆 |
| GET/PUT | `/api/v1/settings` | 系统设置 |
