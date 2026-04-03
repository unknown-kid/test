# AI辅助论文阅读Web系统 — 设计文档

## 1. 系统架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    Nginx (反向代理)                       │
│              静态资源 + API路由转发 + WS代理               │
└──────────┬──────────────────────┬───────────────────────┘
           │                      │
    ┌──────▼──────┐        ┌──────▼──────┐
    │  React SPA  │        │   FastAPI   │
    │  Ant Design │        │  后端服务    │
    │  pdf.js     │        └──┬───┬───┬──┘
    └─────────────┘           │   │   │
                    ┌─────────┘   │   └─────────┐
              ┌─────▼─────┐ ┌────▼────┐  ┌──────▼──────┐
              │ PostgreSQL │ │  Redis  │  │    MinIO     │
              │ 元数据/用户 │ │ 缓存/队列│  │  PDF存储     │
              └───────────┘ └────┬────┘  └─────────────┘
                                 │
                          ┌──────▼──────┐     ┌─────────┐
                          │Celery Worker│────▶│  Milvus  │
                          │ 异步任务处理  │     │ 向量存储  │
                          └──────┬──────┘     └─────────┘
                                 │
                          ┌──────▼──────┐
                          │   CrewAI    │
                          │ 阅读报告生成  │
                          └─────────────┘
```

通信机制：
- 前端↔后端：REST API + WebSocket（实时通知，基于用户维度的连接管理：同一用户多页面各自建立连接，服务端按user_id投递消息，所有连接均可收到，access token初始认证+断线自动重连）+ SSE（AI对话流式输出）
- PDF加载：前端通过后端API中转获取PDF流（非直接访问MinIO）
- Celery→用户通知：Worker通过Redis pub/sub → FastAPI WebSocket handler → 前端
- 新标签页认证：论文详情页通过localStorage共享JWT Token（同域SPA自动共享）

## 2. 模块划分

### 2.1 前端模块

| 模块 | 职责 |
|------|------|
| Auth | 登录/注册/JWT双Token无感刷新，区分管理员和用户入口，localStorage存储Token |
| FileManager | 文件系统浏览（图标+文件名+状态+大小+时间）、虚拟滚动+分页（默认20篇）、批量操作、冲突弹窗、搜索功能（关键词+RAG+级联，始终显示在页面顶部）、一键补全进度条 |
| PaperDetail | pdf.js阅读器（后端中转、原生高亮/批注）+ 统一划词弹出框（复制/高亮/批注/翻译/问AI）+ 右侧交互面板（共享区单一合并面板/个人区四标签页全功能）、session抽屉（确认删除、自动标题）、全局阅读报告附加开关（优先个人报告） |
| AdminPanel | 共享区管理、超参数配置、模型配置（含按类型测试连接）、用户管理、Celery任务看板、系统维护模式开关、管理员密码修改 |
| Settings | 用户个人对话模型配置（含测试连接、清除回退） |
| Notification | 通知按钮+消息列表（已读/未读、手动删除）、基于用户维度的WebSocket连接管理（同一用户多页面共享逻辑通知通道，服务端按user_id投递，各连接均可收到）、access token认证+断线自动重连 |

### 2.2 后端模块

| 模块 | 职责 |
|------|------|
| auth | JWT双Token签发/刷新/验证、注册审批（拒绝即删除）、角色鉴权中间件、预置admin账号、管理员密码修改、维护模式拦截 |
| files | 文件系统CRUD（含文件夹移动/复制/深拷贝异步）、冲突检测、目录计数缓存（同步递归更新，失败后台重试）、10层深度、分页 |
| papers | 论文元数据管理、PDF中转API、处理状态查询、一键补全（当前目录递归+进度推送）、扫描版检测（文本提取为空即判定）与清理 |
| search | 关键词检索（pg_trgm加速正则匹配标题+关键词列表，10万篇论文规模下响应时间<5秒）+ 向量检索（Milvus paper_id过滤+阈值过滤+相似度降序，仅摘要向量）+ 组合检索 |
| chat | AI对话（多session/抽屉/确认删除/ask_ai标识/自动标题）、每轮以最新提问为查询重新RAG+Rerank（P默认5固定chunk+Q默认5 Rerank chunk）、SSE流式、上下文截断（排名靠后优先截断）、60000字符警告 |
| translate | 划词翻译（OpenAI兼容 或 DeepL，二选一），目标语言固定中文 |
| reports | 阅读报告CRUD（Markdown）、CrewAI任务触发、重新生成时完成后替换旧报告（失败保留旧报告） |
| annotations | 高亮/批注（pdf.js原生格式）/笔记（Markdown）的CRUD |
| admin | 超参数管理（仅对新论文生效）、模型配置（含按类型测试连接、嵌入模型更换警告+全量重建）、用户看板（活跃=7天内登录）、移除用户、Celery任务看板、管理员密码修改 |
| tasks | Celery任务编排、并发控制（论文级10篇+模型级64请求）、状态追踪、深拷贝异步（失败全量回滚）、全量向量重建、Celery Beat定时清理通知（按创建时间3天） |
| notify | WebSocket连接管理（基于用户维度，同一用户多页面共享逻辑通知通道，服务端按user_id投递，各连接均可收到、access token认证、断线重连）、Redis pub/sub订阅、通知持久化（已读/未读）、实时推送 |
| maintenance | 系统维护模式管理（仅更换嵌入模型时触发，更换翻译/对话模型不触发；开关、先推送通知再主动关闭所有普通用户WebSocket连接再清空用户refresh token强制登出、仅允许全量重建+模型配置） |
| model_test | 模型连接测试API（按模型类型构建不同payload：对话/嵌入/翻译） |

## 3. 数据存储设计

### 3.1 PostgreSQL 表结构

```
users
├── id, username, password_hash, role(admin/user)
├── status(pending/approved), created_at, last_login
└── custom_chat_api_url, custom_chat_api_key, custom_chat_model_name
注：拒绝注册直接删除记录，不保留rejected状态

folders
├── id, name, parent_id(自引用), zone(shared/personal)
├── owner_id(personal区关联用户, shared区为null)
├── depth(当前层级深度，上限10)
├── paper_count(缓存字段，递归统计论文总数，增删移动时自动更新)
└── created_at

papers
├── id, title, abstract, keywords(JSON), file_size
├── folder_id, minio_object_key
├── processing_status(pending/processing/completed/failed)
├── step_statuses(JSON: 每步状态)
├── uploaded_by, created_at
└── zone(shared/personal)
索引：title和keywords字段使用pg_trgm GIN索引加速正则匹配搜索
注：深拷贝论文直接复制原论文的processing_status和step_statuses

highlights
├── id, paper_id, user_id
├── page, position_data(JSON，pdf.js原生格式)
└── created_at

annotations
├── id, paper_id, user_id
├── page, position_data(JSON，pdf.js原生格式), content
└── created_at

notes
├── id, paper_id, user_id, content(Markdown)
└── created_at, updated_at

chat_sessions
├── id, paper_id, user_id, title(自动取首条消息前N字符)
├── source_type(normal/ask_ai), source_text(划词原文)
└── created_at, updated_at

chat_messages
├── id, session_id, role(user/assistant)
├── content(Markdown), context_chunks(JSON)
└── created_at

reading_reports
├── id, paper_id, user_id(null=系统生成)
├── report_type(system/user), content(Markdown)
├── focus_points(用户关注点文本)
├── status(pending/generating/completed/failed)
└── created_at
注：重新生成时新报告完成后替换旧报告，失败则保留旧报告

system_config
├── key, value, description
└── updated_at

notifications
├── id, user_id, type, content, is_read(默认false)
└── created_at
注：通知按创建时间计算，超过3天自动清理（无论已读未读），由Celery Beat定时任务执行
```

### 3.2 Milvus 集合

| 集合 | 字段 | 说明 |
|------|------|------|
| paper_chunks | paper_id, chunk_index, chunk_text, vector | 论文分块向量，用于RAG检索 |
| paper_abstracts | paper_id, abstract_text, vector | 摘要向量，用于语义搜索 |

- 所有集合的paper_id字段支持过滤查询，RAG/语义搜索时传入目标目录下的paper_id列表限定范围
- 语义搜索仅使用摘要向量，结果按相似度降序排列
- 深拷贝论文以新paper_id重新插入一份向量数据（异步完成）
- 更换嵌入模型后需全量重建所有向量数据

### 3.3 MinIO

```
bucket: papers/
├── shared/{paper_id}.pdf        # 共享区论文
└── personal/{user_id}/{paper_id}.pdf  # 个人区论文（深拷贝产生）
```

- 单个PDF上传上限：100MB
- 存储容量需支持10万篇论文及其相关数据

### 3.4 Redis

- Celery Broker：异步任务消息队列
- 会话缓存：JWT Token黑名单、refresh token存储（按角色区分存储，便于维护模式批量清空用户token）
- 并发计数器：模型请求并发量控制 + 论文级并发量控制（原子计数器）
- Pub/Sub：Celery Worker → FastAPI WebSocket handler 的通知中转
- 维护模式标志：全局维护模式状态存储

## 4. 文件系统设计

### 4.1 虚拟文件系统

- `folders` 表通过 `parent_id` 自引用构建目录树，`depth` 字段限制最大10层
- `papers` 表通过 `folder_id` 挂载到目录下
- `zone` 字段区分共享区/个人区，个人区通过 `owner_id` 隔离
- 文件夹和论文均支持移动/复制操作
- 文件列表支持虚拟滚动+分页（10/20/50/100篇，默认20）
- 每篇论文展示：图标、文件名、状态标签（悬停显示详细步骤）、文件大小、上传时间
- 文件夹论文计数通过 `paper_count` 缓存字段维护，论文增删移动时同步递归更新祖先文件夹计数（失败后台重试，不回滚）
- 搜索功能集成在文件系统页面内（始终显示在页面顶部），默认搜索当前浏览目录

### 4.2 复制机制

- 所有复制操作均为深拷贝（异步Celery任务），包括同区域内复制和跨区复制（共享区→个人区）
  - 复制PDF到MinIO、生成新paper_id、复制元数据和所有5个处理步骤的结果数据
  - 以新paper_id在Milvus中重新插入向量数据
  - 直接复制原论文的processing_status和step_statuses
  - 不复制用户个人数据（高亮、批注、笔记、对话、个人报告），不重新跑5个处理步骤
  - 失败时全量回滚（删除已复制的部分数据），仅保留完整复制成功的论文
  - 空间不足时清理并WebSocket通知

### 4.3 冲突处理

- 同名文件夹：弹窗"全部覆盖"/"全部合并"
- 同名文件：弹窗"全部覆盖"/"全部跳过"
- 串行弹出（先文件夹后文件）

### 4.4 删除事务保证

论文删除涉及PostgreSQL、MinIO、Milvus三个存储：
- 三者的删除操作作为逻辑事务执行
- 任一存储删除失败，提示用户未成功删除，不做部分删除

## 5. 权限管理设计

### 5.1 鉴权流程

```
请求 → 维护模式检查（非admin拒绝，admin仅允许全量重建+模型配置）
    → JWT验证（access token过期则用refresh token无感刷新）
    → 角色提取 → 路由权限校验 → 资源归属校验 → 放行
```

### 5.2 权限规则

| 资源 | 校验逻辑 |
|------|---------|
| 共享区文件操作 | 管理员：全部允许；用户：仅浏览+完整复制到个人区 |
| 个人区文件操作 | 管理员：不可访问；用户：仅限自己的个人区，不可移动到共享区 |
| 共享区论文详情页 | 管理员：不可访问；用户：仅PDF查看+单一合并面板（论文信息+系统报告），无交互功能，可完整复制到个人区 |
| 个人区论文详情页 | 管理员：不可访问；用户：全部功能（四标签页） |
| 一键补全 | 管理员：共享区可触发；用户：仅个人区可触发 |
| 交互数据 | 严格按 user_id 隔离 |
| 系统配置 | 仅管理员可读写 |
| 用户管理 | 仅管理员可操作 |
| 对话模型配置 | 管理员配置默认；用户可配置/清除自己的 |
| 系统维护模式 | 仅管理员可开关，仅在更换嵌入模型时触发（更换翻译/对话模型不触发），维护模式下仅允许全量重建+模型配置 |

### 5.3 API路由权限

- `/api/admin/*` — 需要 `role=admin` 的JWT（含密码修改）
- `/api/admin/maintenance/*` — 维护模式下唯一允许的admin操作路由组（全量重建+模型配置）
- `/api/papers/*`, `/api/chat/*` 等 — 需要 `role=user` 的JWT，维护模式下拒绝
- `/api/auth/*` — 公开（登录/注册/刷新token），维护模式下仅允许admin登录
- `/ws/*` — WebSocket连接，基于用户维度管理（同一用户多页面各自连接，服务端按user_id投递），access token初始认证，支持断线自动重连

### 5.4 用户移除

级联删除：个人区文件夹+论文+MinIO文件+Milvus向量数据+高亮+批注+笔记+对话+个人报告，更新相关文件夹 `paper_count`。需二次确认。

## 6. 核心交互流程

### 6.1 论文上传处理流水线

```
上传PDF(≤100MB) → 类型校验 → 存入MinIO → 创建papers记录
    → 文本提取检测：PyMuPDF+pdfplumber提取文本为空 → 判定扫描版PDF → WebSocket通知 → 删除数据 → 终止
    → Celery任务组（5步全部并行，互不依赖）:
        并行: 分块向量化 | 标题提取 | 摘要提取+向量化 | 关键词提取 | CrewAI阅读报告
        批量去重: 本批次所有标题提取完成后统一去重(重复则WebSocket通知+清理)
        注：阅读报告不依赖前四步数据，独立并行执行（Markdown，关注点同时传入Outline Agent和Detail Agent，共享区用管理员模型，个人区优先用户模型）
    → 每步WebSocket推送状态 → 全部完成status=completed
    → 更新所在文件夹及祖先文件夹的paper_count
```

并发控制：论文级10篇 + 模型级64请求（Redis原子计数器）

### 6.2 AI对话流程

```
用户输入（多session，抽屉列表，ask_ai有标识，标题=首条消息前N字符，删除需确认）
    → 前P个chunk(按index，P默认5) + 每轮向量检索+Rerank取Top-Q(Q默认5)
    → 每轮对话都以用户最新提问为查询，重新进行向量检索和Rerank，重新拼接上下文
    → (可选)全局设置附加阅读报告（优先个人报告，无则用系统报告）
    → 截断：保留提问+历史，从Rerank排名靠后截断（上限100000字符）
    → 历史超60000字符时提醒用户建议新建session
    → LLM（用户模型优先）→ SSE流式 → Markdown渲染 → 保存
```

### 6.3 划词交互流程

```
划词 → 统一弹出框（复制/高亮/批注/翻译/问AI，仅个人区）
    翻译: 调用翻译模型 → 弹出对话框显示原文+译文
    问AI: 向量检索 → Rerank Top-K → 新session(source_type=ask_ai) → 继续提问
```

### 6.4 共享区论文阅读流程

```
打开共享区论文（新标签页，localStorage共享Token）
    → 只读PDF + 单一合并面板：论文信息(不含处理状态) + 系统报告(未完成显示"报告生成中")
    → "复制到个人区"按钮 → 文件夹树选择 → 异步深拷贝 → 完成后WebSocket通知 → 自动跳转个人区文件系统页
```

### 6.5 搜索流程

```
文件系统页面顶部搜索区 → 当前浏览目录 → 搜索 →
关键词: 分号分割 → 每个正则匹配(标题+关键词列表) → AND逻辑 → pg_trgm加速
RAG: 向量化 → Milvus检索(paper_id列表过滤，仅摘要向量) → 相似度≥阈值 → 降序排列
级联: 结果集 → 作为另一搜索范围 → 二次过滤
```

### 6.6 一键补全流程

```
当前目录触发 → 递归扫描未完成论文 → 分批提交(10篇)
    → 前端显示进度条(已处理X/总共Y篇)
    → 权限：用户个人区/管理员共享区
```

### 6.7 深拷贝流程

```
同区域复制或跨区复制（共享区→个人区） → 冲突处理弹窗 → Celery异步:
    复制PDF+新paper_id+元数据+5步处理结果+Milvus向量副本（不复制个人数据）
    → 直接复制原论文的processing_status和step_statuses
    → 任一步骤失败则全量回滚（删除已复制部分）
    → 空间不足则清理+通知 → 成功后更新文件夹paper_count
```

### 6.8 全量向量重建流程

```
管理员更换嵌入模型 → 系统警告不兼容 → 确认后开启系统维护模式（仅更换嵌入模型触发，更换翻译模型或对话模型不触发）
    → WebSocket推送维护通知 → 主动关闭所有普通用户WebSocket连接 → 清空Redis中所有普通用户refresh token → 强制登出
    → Celery异步：遍历所有论文 → 重新分块+向量化 → 替换Milvus数据
    → 受论文级并发控制限制（管理员可提前调高） → WebSocket推送进度
    → 完成后关闭维护模式 → 用户可正常登录
```

### 6.9 阅读报告重新生成流程

```
用户点击"重新生成" → 输入关注点 → CrewAI异步生成（关注点同时传入Outline Agent和Detail Agent，用户模型优先）
    → 生成期间旧报告仍可查看 → 成功后替换旧报告 → 失败则保留旧报告不变
```

## 7. 部署架构

```yaml
services:
  nginx        # 反向代理 + 静态资源 + WebSocket代理
  frontend     # React构建产物
  backend      # FastAPI + Uvicorn（HTTP + WebSocket + SSE）
  celery       # Celery Worker（可多实例扩展）+ Celery Beat（定时任务：通知清理）
  postgresql   # 关系型数据库（含pg_trgm扩展）
  redis        # 缓存 + 消息队列 + Pub/Sub + 维护模式标志
  minio        # 对象存储（容量：10万篇论文）
  milvus       # 向量数据库（含etcd + minio依赖，支持paper_id过滤）
```

所有服务Docker内部网络通信，仅Nginx暴露外部端口。

系统初始化：预置管理员账号（admin/admin123）。

超参数修改仅对后续新论文生效。

通知按创建时间计算，超过3天自动清理，无论已读未读（Celery Beat定时任务）。