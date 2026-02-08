# Docker 部署指南（仅需服务器安装 Docker）

本指南适用于**只安装了 Docker** 的 Linux 服务器，从零部署 Lumist ExamAgent 后端。

---

## 一、前置条件

- 服务器已安装 **Docker** 和 **Docker Compose**（Docker 20.10+ 通常已自带 `docker compose` 命令）
- 本机可 SSH 登录服务器，或将项目拷贝到服务器（如 `git clone`、scp 等）

检查 Docker 是否可用：

```bash
docker --version
docker compose version
```

若没有 `docker compose`，可安装 Docker Compose 插件，或使用旧版 `docker-compose` 命令替代下文的 `docker compose`。

---

## 二、在服务器上准备项目

### 方式 A：Git 克隆（推荐）

```bash
cd /opt   # 或你希望的目录
git clone <你的仓库地址> Lumist_examAgent_backend
cd Lumist_examAgent_backend
```

### 方式 B：本地上传

在本地打包（排除虚拟环境、缓存等）后上传到服务器并解压：

```bash
# 在本地项目根目录
tar --exclude='.git' --exclude='.venv' --exclude='__pycache__' --exclude='data' --exclude='.env' -czvf ../examagent-backend.tar.gz .
# 上传 examagent-backend.tar.gz 到服务器后
mkdir -p /opt/Lumist_examAgent_backend && cd /opt/Lumist_examAgent_backend
tar -xzvf /path/to/examagent-backend.tar.gz
```

---

## 三、配置环境变量

在项目根目录创建 `.env` 文件（必做）：

```bash
cp .env.example .env
```

编辑 `.env`，**至少修改数据库密码**（生产环境务必改掉默认密码）：

```bash
# 例如
POSTGRES_PASSWORD=你的强密码
POSTGRES_DB=lumist_exam_agent
```

其余项可按需修改（如百炼 RAG、嵌入模型等），不修改则使用默认值。

---

## 四、构建并启动

在项目根目录执行：

```bash
docker compose build
docker compose up -d
```

- 首次构建可能较久（安装 Python 依赖、sentence-transformers 等）。
- 首次运行后端时，嵌入模型会从网络下载（约 80MB），国内建议在 `.env` 中设置 `HF_ENDPOINT=https://hf-mirror.com`。

查看服务状态与日志：

```bash
docker compose ps
docker compose logs -f backend
```

---

## 五、初始化数据库（首次部署必做）

PostgreSQL 启动时会自动执行 `sql/schema.sql` 建表。**用户画像等字段**需要再执行一次迁移：

```bash
docker compose exec backend python scripts/run_migration_001_user_profile.py
```

看到成功提示即可。

---

## 六、验证服务

- **健康检查**：`http://服务器IP:8000/api/health`（或你配置的 `API_PREFIX` + `/health`）
- **API 文档**：`http://服务器IP:8000/docs`

若 8000 端口被防火墙拦截，需在安全组/防火墙中放行 TCP 8000（以及可选 6333 若需从外网访问 Qdrant）。

---

## 七、常用命令

| 操作           | 命令 |
|----------------|------|
| 停止所有服务   | `docker compose down` |
| 仅停止不删数据 | `docker compose stop` |
| 查看后端日志   | `docker compose logs -f backend` |
| 进入后端容器   | `docker compose exec backend bash` |
| 重启后端       | `docker compose restart backend` |

---

## 八、数据与持久化

以下数据通过 Docker Volume 持久化，`docker compose down` 不会删除：

- `postgres_data`：PostgreSQL 数据
- `qdrant_data`：Qdrant 向量数据
- `backend_data`：后端上传/文库等文件（`/app/data`）

若需完全清空重来（**会删掉所有数据**）：

```bash
docker compose down -v
```

---

## 九、使用外部数据库或 Qdrant

- **使用外部 PostgreSQL**：在 `.env` 中设置 `DATABASE_URL`，并修改 `docker-compose.yml` 中 `backend` 的 `environment`，去掉或改写 `DATABASE_URL`，且可去掉 `postgres` 服务及 `depends_on` 中的 postgres。
- **使用外部 Qdrant**：在 `.env` 中设置 `QDRANT_URL` 为外部地址，并修改 `docker-compose.yml` 中 `backend` 的 `environment` 中 `QDRANT_URL`，且可去掉 `qdrant` 服务及 `depends_on` 中的 qdrant。

---

## 十、故障排查

1. **后端启动报错找不到数据库**  
   等待 PostgreSQL 健康后再启动后端；`depends_on` 已配置 `condition: service_healthy`，若仍失败可多等几秒后 `docker compose restart backend`。

2. **嵌入模型下载很慢或失败**  
   在 `.env` 中设置 `HF_ENDPOINT=https://hf-mirror.com`，并保证容器能访问外网。

3. **端口被占用**  
   修改 `docker-compose.yml` 中 `backend` 的 `ports`，例如改为 `"8080:8000"`，则访问时用 8080。

4. **需要查看/调试**  
   `docker compose exec backend bash` 进入容器，或 `docker compose logs -f backend` 查看日志。

完成以上步骤后，服务即可在服务器上仅依赖 Docker 运行。
