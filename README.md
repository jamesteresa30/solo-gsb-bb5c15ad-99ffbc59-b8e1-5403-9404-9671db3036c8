# Sealed Predictions — 封存并按时公开预测的 Commit-Reveal 服务

基于 **FastAPI + PostgreSQL** 的预测封存服务：先在截止前提交预测的承诺哈希（SHA-256），
进入揭示期后再公开原文与随机盐，服务端重算哈希校验，**仅首次匹配的揭示生效**，
并提供可核验的事件时间线。所有截止时间均按**服务端 UTC** 判定。

## 快速启动（一条命令）

```bash
docker compose up --build
```

- API 地址：**http://localhost:8000**
- 交互式文档（Swagger UI）：**http://localhost:8000/docs**
- 健康检查：`GET http://localhost:8000/health`

依赖安装与建表均在启动时自动完成：Compose 启动 Postgres 16 与 API 两个容器，
API 等待数据库健康检查后启动，并在启动时自动创建数据表（`events` / `commitments` / `reveals`）。

## 承诺哈希方案

```
commitment = SHA-256( 原文字节长度的 8 字节大端整数 || 原文 UTF-8 字节 || 盐 UTF-8 字节 )
```

8 字节大端长度前缀用于消除「原文 + 盐」拼接歧义。可用服务端工具端点核对本地实现：

```bash
curl -s -X POST http://localhost:8000/utils/commitment \
  -H 'Content-Type: application/json' \
  -d '{"original_text": "明天下雨", "salt": "my-random-salt"}'
# {"commitment_hash": "...", "hash_scheme": "sha256(u64be(len(utf8(text))) || utf8(text) || utf8(salt))"}
```

## 事件生命周期（服务端 UTC 判定）

| 阶段 | 时间区间 | 允许操作 |
|------|----------|----------|
| `commit` | 创建时刻 ≤ now < commit_deadline | 提交承诺 |
| `reveal` | commit_deadline ≤ now < reveal_deadline | 提交揭示 |
| `closed` | now ≥ reveal_deadline | 只读 |

边界语义：到达 commit_deadline 的瞬间提交通道关闭、揭示通道开启；到达 reveal_deadline 揭示通道关闭。

## API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/events` | 创建事件（commit_deadline 须在未来，reveal_deadline 须更晚） |
| GET | `/events` | 事件列表（含状态与计数） |
| GET | `/events/{id}` | 事件详情 |
| POST | `/events/conflicts` | 事件窗口冲突分析（commit/reveal 半开区间的 sweep-line 重叠检测） |
| POST | `/events/{id}/commitments` | 提交承诺（64 位十六进制哈希） |
| GET | `/events/{id}/commitments` | 承诺列表（含是否已揭示） |
| POST | `/events/{id}/reveals` | 揭示：提交原文 + 盐，服务端重算校验 |
| GET | `/events/{id}/timeline` | 可核验的事件时间线 |
| POST | `/utils/commitment` | 按约定方案计算承诺哈希 |
| GET | `/health` | 健康检查 |

## 完整使用示例

```bash
# 1. 创建事件（截止时间须携带时区）
curl -s -X POST http://localhost:8000/events \
  -H 'Content-Type: application/json' \
  -d '{"title": "我的预测", "commit_deadline": "2030-01-01T00:00:00Z", "reveal_deadline": "2030-01-02T00:00:00Z"}'
# => {"id": "<EVENT_ID>", "status": "commit", ...}

# 2. 本地计算承诺（Python 参考实现）
python3 - <<'EOF'
import hashlib
text, salt = "明天下雨", "my-random-salt"
tb = text.encode("utf-8")
print(hashlib.sha256(len(tb).to_bytes(8, "big") + tb + salt.encode()).hexdigest())
EOF

# 3. 提交截止前提交承诺
curl -s -X POST http://localhost:8000/events/<EVENT_ID>/commitments \
  -H 'Content-Type: application/json' \
  -d '{"commitment_hash": "<64位十六进制哈希>"}'

# 4. 进入揭示期后提交原文与盐
curl -s -X POST http://localhost:8000/events/<EVENT_ID>/reveals \
  -H 'Content-Type: application/json' \
  -d '{"original_text": "明天下雨", "salt": "my-random-salt"}'
# => {"verified": true, "recomputed_hash": "...", "commitment_hash": "...", ...}

# 5. 获取可核验时间线（含原文与盐，任何人可重算哈希比对）
curl -s http://localhost:8000/events/<EVENT_ID>/timeline
```

## 事件窗口冲突分析

`POST /events/conflicts` 接收事件 ID 列表，把每个事件按服务端 UTC 拆成两个
**半开区间**（commit：`[created_at, commit_deadline)`，reveal：
`[commit_deadline, reveal_deadline)`），用 sweep-line 找出任意时刻同时处于
同一阶段的事件集合，返回极大的冲突片段：

```bash
curl -s -X POST http://localhost:8000/events/conflicts \
  -H 'Content-Type: application/json' \
  -d '{"event_ids": ["<EVENT_ID_1>", "<EVENT_ID_2>", "<EVENT_ID_3>"]}'
```

```json
{
  "generated_at": "2026-09-22T08:00:00Z",
  "event_count": 3,
  "conflicts": [
    {
      "phase": "commit",
      "start": "2026-09-22T08:00:01.123456Z",
      "end": "2030-01-01T00:00:00Z",
      "event_ids": ["<EVENT_ID_1>", "<EVENT_ID_2>"]
    },
    {
      "phase": "reveal",
      "start": "2030-01-02T00:00:00Z",
      "end": "2030-01-03T00:00:00Z",
      "event_ids": ["<EVENT_ID_1>", "<EVENT_ID_3>"]
    }
  ]
}
```

- 片段按 `(start, end, phase)` 排序，片段内事件 ID 按字典序排列，输出稳定；
- 半开边界：仅在端点处相接的窗口**不构成**冲突；无冲突时 `conflicts` 稳定为 `[]`；
- 重复 ID 自动去重；列表中含不存在的 ID 时返回 404 `EVENT_NOT_FOUND`。

## 错误响应

错误统一返回 `{"detail": {"code": "...", "message": "..."}}`，且**均不改变任何状态**
（所有校验先于写入，并发冲突由数据库唯一约束兜底并回滚）：

| HTTP | code | 场景 |
|------|------|------|
| 400 | `INVALID_DEADLINES` | 截止时间顺序非法或 commit_deadline 不在未来 |
| 404 | `EVENT_NOT_FOUND` | 事件不存在 |
| 409 | `COMMIT_PHASE_CLOSED` | 迟到提交（已过 commit_deadline） |
| 409 | `DUPLICATE_COMMITMENT` | 同一事件内重复的承诺哈希 |
| 409 | `REVEAL_PHASE_NOT_STARTED` | 提前揭示（未到 commit_deadline） |
| 409 | `REVEAL_PHASE_CLOSED` | 逾期揭示（已过 reveal_deadline） |
| 409 | `NO_MATCHING_COMMITMENT` | 原文 + 盐重算后不匹配任何承诺 |
| 409 | `DUPLICATE_REVEAL` | 该承诺已被揭示（仅首次匹配生效） |
| 422 | — | 请求体格式校验失败（如哈希非 64 位十六进制） |

「仅首次匹配的揭示生效」由 `reveals.commitment_id` 唯一约束保证：并发揭示同一承诺时，
后到者事务回滚并收到 `DUPLICATE_REVEAL`。

## 本地开发与测试

```bash
pip install -r requirements-dev.txt
DATABASE_URL=sqlite:///./dev.db uvicorn app.main:app --reload   # 本地运行（默认连 PostgreSQL）
python3 -m pytest tests/ -q                                     # 运行测试（SQLite + 模拟时钟）
```

## 项目结构

```
app/
  main.py       # 路由、生命周期、时间判定与错误处理
  conflicts.py  # 事件窗口冲突分析（sweep-line）
  models.py     # SQLAlchemy 模型（events / commitments / reveals）
  schemas.py    # Pydantic 请求/响应模型
  hashing.py    # 承诺哈希方案实现
  database.py   # 引擎与会话（DATABASE_URL 可配置）
tests/
  test_api.py        # 业务规则冒烟测试（SQLite + 模拟时钟）
  test_conflicts.py  # sweep-line 冲突分析单元测试
Dockerfile
docker-compose.yml
requirements.txt / requirements-dev.txt
```
