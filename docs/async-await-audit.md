# 全链路 async/await 异步编程符合性检查报告

本文档汇总当前代码库与「全链路采用 async/await 异步编程模式」的差异，仅作问题记录，不包含修改方案实现。

---

## 一、总体结论

**当前项目整体为同步（sync）模型，仅少数接口或调用点使用了 `async def` / `await`，未形成全链路异步。**

- 数据库：同步 SQLAlchemy + `psycopg2`
- 外部 HTTP/LLM：同步 OpenAI 客户端、同步百炼检索
- 文件 I/O：同步 `open()` / `Path.read_text()` / `write_text()`
- 路由：多数为 `def`，仅个别为 `async def`，且 `async def` 内仍调用大量同步阻塞逻辑

---

## 二、API 路由层

| 文件 | 接口/函数 | 当前定义 | 说明 |
|------|------------|----------|------|
| `app/api/routes/exercises.py` | `analyze` | `def` | 同步，内部调 LLM + DB |
| `app/api/routes/exercises.py` | `analyze_file` | `async def` | 唯一使用 `await file.read()`，其余为同步 |
| `app/api/routes/exercises.py` | `generate_from_text` | `def` | 同步，内建同步生成器 + RAG + DB |
| `app/api/routes/exercises.py` | `get_exercise_detail` | `def` | 同步，仅 DB 查询 |
| `app/api/routes/exercises.py` | `submit_exercise` | `def` | 同步，仅 DB |
| `app/api/routes/exercises.py` | `delete_exercise` | `def` | 同步，仅 DB |
| `app/api/routes/exercises.py` | `list_exercises` | `def` | 同步，仅 DB |
| `app/api/routes/user.py` | `get_profile` | `def` | 同步，仅 DB |
| `app/api/routes/user.py` | `update_profile` | `def` | 同步，仅 DB |
| `app/api/routes/docs.py` | `upload_material` | `async def` | 仅 `UploadFile` 为异步入口，内部 `get_or_create_dev_user`、`save_upload`、`db.add/commit` 均为同步 |
| `app/api/routes/docs.py` | `upload_doc` | `async def` | 同上 |
| `app/api/routes/docs.py` | `get_doc_file` | `def` | 同步 |
| `app/api/routes/docs.py` | `get_doc` | `def` | 同步 |
| `app/api/routes/docs.py` | `list_docs` | `def` | 同步 |
| `app/api/routes/docs.py` | `parse_doc` | `def` | 同步，内部含 LLM、embedding、Qdrant、文件 I/O |
| `app/api/routes/docs.py` | `delete_doc` | `def` | 同步 |
| `app/api/routes/health.py` | `health_check` | `def` | 同步，无 I/O |

**问题小结：**

- 绝大部分路由为 `def`，在 FastAPI 中会在线程池执行，易在高并发下占满线程池。
- 仅 `analyze_file`、`upload_material`、`upload_doc` 为 `async def`，且其内部仍调用同步 DB、同步文件、同步 HTTP，事件循环会被阻塞，未形成真正异步链路。

---

## 三、数据库层

| 文件 | 内容 | 说明 |
|------|------|------|
| `app/core/db.py` | `create_engine(..., future=True)` | 同步引擎 |
| `app/core/db.py` | `SessionLocal = sessionmaker(bind=engine, ...)` | 同步 Session 工厂 |
| `app/core/db.py` | `get_db()` 为 `def`，`yield db` | 同步依赖，无 `async def` / `AsyncSession` |
| 各处路由/服务 | `db.query(...)`、`db.add()`、`db.commit()`、`db.refresh()` | 均为同步调用，会阻塞事件循环 |

**问题小结：**

- 未使用 `asyncpg` 或 `greenlet` 等异步驱动。
- 未使用 SQLAlchemy 2.0 的 `AsyncSession`、`async with get_db()` 等异步会话模式。
- 所有涉及 DB 的接口（练习、用户、文档等）在请求处理期间都会发生同步阻塞。

---

## 四、外部服务与 I/O

### 4.1 大模型 / HTTP 客户端

| 文件 | 调用方式 | 说明 |
|------|----------|------|
| `app/services/llm_service.py` | `get_openai_client()` 返回同步 `OpenAI` | 同步客户端 |
| `app/services/llm_service.py` | `client.chat.completions.create(...)` | 同步阻塞，无 `await` |
| `app/services/exercise_service.py` | `client.chat.completions.create(..., stream=True)`，`for chunk in completion` | 同步流式，阻塞 |
| `app/services/file_analyze_service.py` | `client.files.create(...)`、`client.chat.completions.create(...)` | 同步阻塞 |
| `app/services/bailian_retrieve_service.py` | `client.retrieve(workspace_id, request)` | 百炼 SDK 同步调用，阻塞 |

**问题小结：**

- 未使用 `openai.AsyncOpenAI` 或 `httpx.AsyncClient` 等异步 HTTP。
- 分析材料、生成题目、文件分析、文档总结、RAG 检索等路径均存在同步网络阻塞。

### 4.2 文件 I/O

| 文件 | 调用方式 | 说明 |
|------|----------|------|
| `app/main.py` | `open(_env, "r", encoding="utf-8")` | 同步读 .env |
| `app/services/file_analyze_service.py` | `open(path, "rb")`、`client.files.create(file=f, ...)` | 同步读文件 + 同步上传 |
| `app/api/routes/exercises.py` | `tmp.write(normalized_bytes)`、`open(path, "w", encoding="utf-8")`（RAG 调试） | 同步写 |
| `app/services/doc_parse_service.py` | `_load_text`、`_load_pptx_text`、`Path(...).read_text()`、`write_text()` | 同步读/写 |
| `app/services/storage_service.py` | `target_path.open("wb")`、`file_obj.read(...)` | 同步 |
| `scripts/run_migration_001_user_profile.py` | `open(_env_file, ...)`、`sql_file.read_text()` | 同步（脚本可保持同步） |

**问题小结：**

- 未使用 `aiofiles` 或 `run_in_executor` 包装文件操作，所有文件 I/O 均在主线程/事件循环中同步执行。

### 4.3 向量库 / Embedding

| 文件 | 调用方式 | 说明 |
|------|----------|------|
| `app/services/qdrant_service.py` | `QdrantClient(...)`、`client.upsert(...)`、`client.delete(...)` | 同步 Qdrant 客户端 |
| `app/services/embedding_service.py` | `SentenceTransformer(...)`、`model.encode(texts)` | CPU/GPU 同步计算，耗时长 |

**问题小结：**

- Qdrant 与 embedding 均为同步调用，`parse_doc` 等链路会长时间占用工作线程/进程。

---

## 五、流式响应

| 文件 | 实现 | 说明 |
|------|------|------|
| `app/services/exercise_service.py` | `stream_raw_and_collect` 为同步生成器 `Iterator[str \| dict]`，内部 `for chunk in completion` | 同步迭代 LLM 流，阻塞 |
| `app/api/routes/exercises.py` | `_stream_generate` 为同步生成器，`def gen(): return _stream_generate(...)`，`StreamingResponse(gen())` | FastAPI 会将同步生成器放入线程池执行，流式期间该线程被占用 |

**问题小结：**

- 流式生成题目全流程为同步；若改为全链路异步，应使用 `async def` 生成器 + `AsyncOpenAI` 的异步流式 API，避免占用线程池。

---

## 六、依赖注入与中间件

| 文件 | 内容 | 说明 |
|------|------|------|
| `app/core/db.py` | `get_db()` 为同步生成器 | 无法在异步上下文中 `await get_db()`，与 AsyncSession 不匹配 |
| `app/main.py` | `await call_next(request)` | 仅中间件内使用 `await`，应用逻辑仍以同步为主 |

---

## 七、建议排查与改造顺序（仅列出方向，不实现）

1. **数据库**：引入 `asyncpg`，使用 SQLAlchemy 2.0 `AsyncEngine` / `AsyncSession`，将 `get_db` 改为 `async def` 并 `yield` AsyncSession。
2. **路由**：所有涉及 I/O 的路由改为 `async def`，并在其中使用 `await` 调用异步 DB/HTTP/文件。
3. **LLM / 百炼**：使用 `openai.AsyncOpenAI` 或 `httpx.AsyncClient` 封装异步请求；流式使用异步迭代器。
4. **文件 I/O**：使用 `aiofiles` 或 `asyncio.to_thread`（`run_in_executor`）包装同步文件操作。
5. **Embedding / Qdrant**：使用 `asyncio.to_thread` 包装 CPU 密集的 `embed_texts`；Qdrant 若提供异步客户端可替换为异步调用。
6. **流式生成**：`stream_raw_and_collect` 改为 `async def` 生成器，内部 `async for chunk in completion`，`StreamingResponse` 使用异步生成器。

---

## 八、涉及文件清单（便于后续按文件改造）

- `app/main.py` — .env 读取、中间件
- `app/core/db.py` — 引擎与 Session、get_db
- `app/api/routes/exercises.py` — 练习相关路由与流式生成
- `app/api/routes/docs.py` — 文档上传/解析/列表/删除
- `app/api/routes/user.py` — 用户资料
- `app/api/routes/health.py` — 健康检查
- `app/services/llm_service.py` — 大模型调用
- `app/services/exercise_service.py` — 分析材料、流式生成题目、解析落库
- `app/services/file_analyze_service.py` — 文件上传与 qwen-long 分析
- `app/services/bailian_retrieve_service.py` — 百炼检索
- `app/services/doc_parse_service.py` — 文档解析与向量化
- `app/services/embedding_service.py` — 向量化
- `app/services/qdrant_service.py` — Qdrant 写入/删除
- `app/services/storage_service.py` — 文件存储
- `app/repositories/user_repository.py` — 用户查询/创建

---

*文档生成目的：对照「全链路 async/await 异步编程」要求做差异记录，供后续迭代改造时使用。*
