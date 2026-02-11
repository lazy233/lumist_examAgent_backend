# 并发控制建议

本文档基于当前代码梳理：**哪里需要做并发控制**、**为什么**、以及**可选实现方式**。按优先级与实现成本排序。

---

## 一、强烈建议（易出问题）

### 1. 文档解析：同一文档禁止并发解析

**位置**：`POST /docs/{doc_id}/parse`（`app/api/routes/docs.py`）

**问题**：

- 未校验 `doc.status`，同一 `doc_id` 被多次点击或重复请求时，会同时跑多路解析。
- 多路解析会：重复调用大模型、重复写 `doc.parsed_*` 和 `doc.status`，最后谁后 commit 谁覆盖，结果不可预期；若其中一路失败把 `status` 改为 `failed`，可能覆盖另一路已成功的 `done`。

**建议**：

- **入口校验**：若 `doc.status == "parsing"`，直接返回 `409 Conflict` 或 `400`，提示「该文档正在解析中，请勿重复发起」。
- **可选**：用 **Redis 分布式锁**（key 如 `parse:doc:{doc_id}`，TTL 略大于单次解析最长时间），在进入解析前加锁，解析结束或异常时释放，避免多实例部署下仍并发解析同一文档。

**示例（仅状态校验）**：

```python
# POST /docs/{doc_id}/parse 开头
if doc.status == "parsing":
    raise HTTPException(status_code=409, detail="该文档正在解析中，请勿重复发起")
```

---

### 2. 删除资料：解析中禁止删除

**位置**：`DELETE /docs/{doc_id}`（`app/api/routes/docs.py`）

**问题**：

- 若 A 正在请求 `POST /docs/{doc_id}/parse`（流式未结束），B 请求 `DELETE /docs/{doc_id}`，会删掉磁盘文件并删掉 `doc` 记录。
- 解析流仍在读 `file_path`、写 `doc`，会导致：读文件失败、或 commit 时记录已被删，产生异常或脏数据。

**建议**：

- 删除前若 `doc.status == "parsing"`，直接返回 `409`，提示「文档正在解析中，请解析完成后再删除」。
- 若希望「删除即取消解析」，则需在解析侧轮询或订阅「文档是否已删除」，并在删除时等待/取消解析（实现成本较高，一般先做「解析中不可删」即可）。

---

### 3. 开发用户创建：并发下唯一性

**位置**：`get_or_create_dev_user`（`app/repositories/user_repository.py`），被多数接口通过 `get_or_create_dev_user(db)` 调用。

**问题**：

- 两个请求同时发现没有 `id=DEV_USER_ID` 的用户，会各自 `db.add(user)` 并 `commit()`，第二个会触发唯一约束冲突（`users.id` 或 `users.username` 为 `dev`）。
- 当前未捕获 `IntegrityError`，第二个请求会 500。

**建议**：

- 在 `get_or_create_dev_user` 里捕获 `IntegrityError`（及 DB 的唯一约束异常），在冲突时重新 `select` 一次并返回已存在的用户。

**示例**：

```python
async def get_or_create_dev_user(db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.id == DEV_USER_ID))
    user = result.scalars().first()
    if user:
        return user
    user = User(id=DEV_USER_ID, name="Dev User", username="dev", password_hash="placeholder")
    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
        return user
    except Exception as e:
        await db.rollback()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():  # 或使用 SQLAlchemy IntegrityError
            result = await db.execute(select(User).where(User.id == DEV_USER_ID))
            return result.scalars().first()
        raise
```

（实际建议用 `from sqlalchemy.exc import IntegrityError` 做 `except IntegrityError`。）

---

## 二、建议（资源与一致性）

### 4. 大模型/百炼调用：限流与排队

**位置**：所有调用 LLM 或百炼的接口，例如：

- `POST /exercises/analyze`
- `POST /exercises/analyze-file`
- `POST /exercises/generate-from-text`
- `POST /docs/{doc_id}/parse` 内部（`doc_parse_service`）

**问题**：

- 并发请求过多会打满第三方 QPS、触发限流或 5xx，或把本机内存/连接占满。
- 无全局/每用户并发上限时，难以做容量规划和稳定性保障。

**建议**：

- 使用 **asyncio.Semaphore** 限制「同时进行中的 LLM 调用数」（例如全局限 5，或按用户限 2）。
- 在进入「调用大模型/百炼」的逻辑前 `async with semaphore`，调用结束自动释放。可单独建一个 `app/core/llm_concurrency.py` 管理 semaphore，供各 service 使用。

---

### 5. 练习提交：是否允许重复提交

**位置**：`POST /exercises/{exercise_id}/submit`（`app/api/routes/exercises.py`）

**现状**：每次提交都会插入一条新的 `ExerciseResult`，同一练习可多次提交、多次得分。

**是否需要并发控制**：

- 若业务允许「多次作答、取最后一次或最高分」，当前设计无需改。
- 若业务要求「每个用户每个练习只允许提交一次」，则需要：
  - 在 `(exercise_id, owner_id)` 上做唯一约束（或唯一索引），或
  - 提交前查询是否已有该用户该练习的提交记录，有则返回 409 或覆盖策略（需明确产品逻辑）。

---

## 三、可选（按需）

### 6. 文档上传：同一用户短时间大量上传

若担心同一用户瞬间上传大量文件占满磁盘或拖垮服务，可做：

- 全局限流：如 Nginx / API Gateway 按 IP 或 token 限流。
- 或应用内按 `owner_id` 限流：如 Redis 计数，每分钟最多 M 次上传，超限返回 429。

### 7. 练习生成中的「按文档出题」

当前路由里只有「按文字流式出题」`/exercises/generate-from-text`；若后续有「按 doc_id 异步出题」的接口（类似设计文档里的 `POST /exercises/generate`），建议：

- 同一 `doc_id` 同时只允许一个「正在生成」的练习（或通过状态 + 唯一约束/分布式锁保证），避免同一文档被并发拉取、重复生成多份练习导致混乱。

---

## 小结

| 场景               | 位置                         | 建议措施                                         | 优先级 |
|--------------------|------------------------------|--------------------------------------------------|--------|
| 同一文档重复解析   | `POST /docs/{doc_id}/parse`  | 状态校验（parsing 直接 409）；可选 Redis 锁     | 高     |
| 解析中删除文档     | `DELETE /docs/{doc_id}`      | 若 status==parsing 则 409                        | 高     |
| 并发创建 dev 用户  | `get_or_create_dev_user`     | 捕获 IntegrityError 后重试 select               | 高     |
| 大模型/百炼并发    | 各 LLM 调用入口              | 全局限流 Semaphore（及按用户可选）               | 中     |
| 练习多次提交       | `POST .../submit`            | 若业务要求「只允许一次」则加唯一约束或校验       | 按产品 |
| 上传/按 doc 出题   | 上传接口、未来按 doc 出题    | 按需限流或锁                                     | 低     |

实现时建议先做 **1、2、3**，再视部署规模和稳定性需求加 **4**；**5、6、7** 按产品与运维需求决定是否做。
