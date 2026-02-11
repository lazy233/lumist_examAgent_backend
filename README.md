# Lumist ExamAgent Backend

AI 出题与练习后端服务：基于 FastAPI + PostgreSQL，支持文档上传与解析、RAG 知识库检索、大模型流式出题、作答提交与智能批改。

---

## 功能概览

| 模块 | 说明 |
|------|------|
| **认证** | JWT 登录/注册，Token 鉴权 |
| **资料** | 文档上传（PDF/DOCX/PPTX/TXT）、解析与结构化总结（学校/专业/课程/知识点/摘要）、资料列表与删除 |
| **出题** | 文字材料分析（要点提炼）→ 确认后流式生成题目；支持单选/多选/判断/填空/简答，可配置难度与数量 |
| **RAG** | 接入阿里云百炼知识库，出题前检索相关片段并经 LLM 梳理后作为上下文，提升题目与知识库的一致性 |
| **练习** | 练习详情、提交答案、客观题自动判分、简答题等由 LLM 批改与解析，练习列表与删除 |
| **个人** | 用户信息与偏好（可选） |

---

## 技术栈

- **框架**：FastAPI
- **数据库**：PostgreSQL（SQLAlchemy + asyncpg）
- **缓存**：Redis（设计预留）
- **文档与 LLM**：LangChain（文档加载）、OpenAI 兼容 API（阿里云百炼 / DashScope）、阿里云百炼知识库（RAG 检索）
- **文件**：本地文件系统（上传目录、资料库目录）
- **部署**：Docker + Docker Compose

---

## 项目结构

```
Lumist_examAgent_backend/
├── app/
│   ├── main.py              # FastAPI 入口、中间件
│   ├── api/
│   │   ├── router.py        # 路由聚合
│   │   ├── deps.py          # 依赖注入
│   │   └── routes/          # 认证、资料、练习、健康、用户
│   ├── core/
│   │   ├── config.py        # 配置（环境变量）
│   │   ├── db.py            # 数据库会话
│   │   ├── security.py      # JWT、密码哈希
│   │   └── storage.py       # 存储目录初始化
│   ├── models/              # SQLAlchemy 模型（users, docs, exercises, questions, answers, exercise_results）
│   ├── repositories/        # 用户等数据访问
│   ├── schemas/             # Pydantic 模型（按需）
│   └── services/            # 业务逻辑：文档解析、出题、RAG、LLM、存储
├── sql/
│   ├── schema.sql           # 建表语句
│   └── migrations/           # 增量迁移（如 users 个人中心、题目类型等）
├── scripts/                 # 迁移执行脚本、清理脚本
├── docs/                    # 部署、并发控制等文档
├── docker-compose.yml       # 后端 + PostgreSQL 编排
├── Dockerfile
├── requirements.txt
├── .env.example             # 环境变量示例
└── README.md
```

---

## 环境要求

- **Python**：3.11+（推荐，以兼容部分依赖）
- **PostgreSQL**：14+（或使用 Docker 中的 Postgres）
- **可选**：Redis（当前未强制使用）、阿里云百炼账号（RAG 与 LLM 需配置 Key）

---

## 本地运行

### 1. 克隆与依赖

```bash
git clone https://github.com/lazy233/lumist_examAgent_backend.git Lumist_examAgent_backend
cd Lumist_examAgent_backend

# 建议使用虚拟环境
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 环境变量

在项目根目录创建 `.env` 文件（可复制 `.env.example` 后修改）：

```bash
cp .env.example .env
```

**必改（生产）**：

- `SECRET_KEY`：JWT 签名密钥，请设为强随机字符串
- `POSTGRES_PASSWORD`：若用 Docker 部署，数据库密码

**常用**：

| 变量 | 说明 | 默认示例 |
|------|------|----------|
| `DATABASE_URL` | PostgreSQL 连接串（asyncpg） | `postgresql+asyncpg://postgres:password@localhost:5432/lumist_exam_agent` |
| `API_PREFIX` | API 前缀 | `/api` |
| `SECRET_KEY` | JWT 密钥 | 生产务必修改 |
| `WORKSPACE_ID` / `BAILIAN_INDEX_ID` | 百炼 RAG 业务空间与知识库 ID | 为空则出题不走 RAG |
| `OPENAI_API_KEY` | 大模型 API Key（如 DashScope） | 出题/解析依赖 |
| `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET` | 百炼 RAG 检索 | 可选 |
| `LLM_MODEL` / `FILE_ANALYZE_MODEL` | 出题与文件解析所用模型名 | `qwen-long` |
| `DATA_ROOT` / `UPLOAD_DIR` / `LIBRARY_DIR` | 数据与上传、资料库目录 | `data`、`data/upload`、`data/library` |

其余见 `.env.example` 与 `app/core/config.py`。

### 3. 数据库

**本地已有 PostgreSQL 时**：

1. 创建数据库（如 `lumist_exam_agent`）。
2. 执行建表与迁移：
   ```bash
   # 按你本地方式执行 sql/schema.sql，再执行 sql/migrations/*.sql
   # 或使用应用内逻辑（若提供）初始化
   ```
3. 若表已存在但缺少迁移字段，可执行：
   ```bash
   python scripts/run_migration_001_user_profile.py
   python scripts/run_migration_002_exercise_question_type.py
   ```
   脚本会从项目根目录 `.env` 读取 `DATABASE_URL`。迁移脚本使用同步连接，若 `DATABASE_URL` 为 `postgresql+asyncpg://...`，请临时改为 `postgresql+psycopg2://...`（需安装 `psycopg2-binary`），或直接在数据库中执行 `sql/migrations/` 下对应 SQL 文件。

**无本地 Postgres 时**：可直接用 Docker 启动数据库与后端（见下文「Docker 部署」）。

### 4. 启动服务

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- 健康检查：<http://localhost:8000/api/health>
- Swagger 文档：<http://localhost:8000/docs>
- 接口前缀：`/api`（见 `API_PREFIX`）

---

## API 概要

- **认证**：`POST /api/auth/login`、注册等（见路由）
- **健康**：`GET /api/health`
- **资料**：`POST /api/docs/upload`、`POST /api/docs/{doc_id}/parse`、`GET /api/docs/{doc_id}`、`GET /api/docs`、`DELETE /api/docs/{doc_id}` 等
- **练习**：`POST /api/exercises/analyze`、`POST /api/exercises/generate-from-text`、`GET /api/exercises/{id}`、`POST /api/exercises/{id}/submit`、`GET /api/exercises` 等
- **用户**：`/api/user` 下个人中心相关（若有）

请求除登录外需在 Header 中携带：`Authorization: Bearer <token>`。接口与字段细节以 Swagger `/docs` 及后端接口实现为准。

---

## Docker 部署

仅需服务器安装 Docker（与 Docker Compose），即可一键部署后端与 PostgreSQL：

```bash
cp .env.example .env
# 编辑 .env，至少设置 POSTGRES_PASSWORD 等

docker compose build
docker compose up -d
```

- 首次启动会自动执行 `sql/schema.sql` 与 `sql/migrations/` 下迁移，无需单独建库。
- 服务端口默认 8000；健康检查：`http://<服务器IP>:8000/api/health`，文档：`http://<服务器IP>:8000/docs`。

详细步骤、数据卷、外部数据库、故障排查见 **[docs/DEPLOY.md](docs/DEPLOY.md)**。

---

## 文档索引

| 文档 | 说明 |
|------|------|
| [docs/DEPLOY.md](docs/DEPLOY.md) | Docker 部署指南（从零到上线） |
| [docs/concurrency-control.md](docs/concurrency-control.md) | 并发控制建议（解析/删除/用户创建/LLM 限流等） |
| [docs/async-await-audit.md](docs/async-await-audit.md) | 异步与 await 使用说明（如有） |

---

## 仓库与协作

- 仓库：<https://github.com/lazy233/lumist_examAgent_backend>（请替换为实际地址）
- 主分支建议通过 **Pull Request** 合并，便于 Code Review。

---

