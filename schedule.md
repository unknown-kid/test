# AI辅助论文阅读Web系统 — 实现进度

## Phase 1: 项目脚手架 + Docker基础设施 + 数据库Schema
- [x] docker-compose.yml (PostgreSQL, Redis, MinIO, Milvus, etcd, Nginx, backend, celery, celery-beat, frontend)
- [x] .env 环境变量
- [x] nginx.conf (HTTP + WS + SSE代理)
- [x] init-scripts/01-extensions.sql (pg_trgm)
- [x] 后端: Dockerfile, requirements.txt, config.py, database.py
- [x] 后端: 全部ORM models (user, folder, paper, interaction, chat, report, config, notification)
- [x] 后端: main.py (FastAPI + Milvus集合初始化 + /api/health)
- [x] 后端: Celery app stub
- [x] Alembic配置 + 初始迁移 (全部表 + pg_trgm索引)
- [x] 前端: Vite + React + TypeScript + Ant Design 项目骨架
- [x] 前端: App.tsx 路由骨架 (全部页面占位)
- [x] schedule.md

## Phase 2: 认证系统
- [x] 后端: schemas/auth.py, schemas/user.py
- [x] 后端: services/auth_service.py (JWT双Token, 密码哈希, Redis refresh存储)
- [x] 后端: services/init_service.py (预置admin + 17项默认配置)
- [x] 后端: dependencies.py (get_current_user, require_admin, require_user, 维护模式检查)
- [x] 后端: routers/auth.py (注册/登录/admin登录/刷新/登出/改密)
- [x] 后端: utils/redis_client.py
- [x] 前端: api/client.ts (axios + token刷新拦截器)
- [x] 前端: api/auth.ts
- [x] 前端: stores/authStore.ts
- [x] 前端: Login.tsx, Register.tsx, admin/AdminLogin.tsx, ProtectedRoute.tsx

## Phase 3: 文件系统
- [x] 后端: schemas/folder.py, schemas/paper.py
- [x] 后端: services/file_service.py (文件夹CRUD, CTE递归, paper_count)
- [x] 后端: services/paper_service.py (上传/删除/移动/批量删除)
- [x] 后端: services/minio_service.py, services/milvus_service.py
- [x] 后端: routers/files.py, routers/papers.py
- [x] 后端: utils/pagination.py
- [x] 前端: api/files.ts
- [x] 前端: stores/fileStore.ts
- [x] 前端: Papers.tsx, FileList.tsx, FolderTree.tsx, BatchActions.tsx
- [x] 前端: ConflictDialog.tsx, UploadDialog.tsx

## Phase 4: 论文上传异步处理流水线
- [x] 后端: tasks/celery_app.py (Celery配置 + Beat定时清理)
- [x] 后端: tasks/processing.py (主编排: 文本提取→扫描检测→5步并行group)
- [x] 后端: tasks/chunking.py, title_extraction.py, abstract_extraction.py
- [x] 后端: tasks/keyword_extraction.py, report_generation.py
- [x] 后端: tasks/deep_copy.py (MinIO+Milvus+PG全量复制+回滚)
- [x] 后端: tasks/cleanup.py, tasks/vector_rebuild.py
- [x] 后端: services/llm_service.py, services/embedding_service.py
- [x] 后端: utils/text_extraction.py, utils/chunking.py, utils/concurrency.py
- [x] 后端: utils/websocket_manager.py (Redis pub/sub通知)
- [x] 前端: StatusTag.tsx, ReprocessButton.tsx

## Phase 5: 搜索系统
- [x] 后端: schemas/search.py
- [x] 后端: services/search_service.py (关键词pg_trgm + RAG Milvus + 级联)
- [x] 后端: routers/search.py
- [x] 前端: api/search.ts
- [x] 前端: SearchBar.tsx (关键词+RAG+级联+方向选择)

## Phase 6: 论文详情页
- [x] 后端: routers/annotations.py
- [x] 后端: schemas/annotation.py
- [x] 前端: PaperDetail.tsx (共享只读 + 个人四标签页)
- [x] 前端: api/annotations.ts

## Phase 7: AI对话 + 翻译
- [x] 后端: routers/chat.py (Session CRUD + SSE streaming)
- [x] 后端: routers/translate.py (OpenAI兼容 + DeepL)
- [x] 后端: schemas/chat.py
- [x] 后端: services/chat_service.py (固定chunks + Rerank + SSE流式)
- [x] 前端: api/chat.ts (SSE streamChat)
- [x] 前端: api/translate.ts
- [x] 前端: ChatPanel.tsx (多session, 抽屉列表, 流式渲染, 附加报告开关)
- [x] 前端: TranslateDialog.tsx
- [x] PaperDetail.tsx集成ChatPanel + TranslateDialog

## Phase 8: 阅读报告
- [x] 后端: schemas/report.py
- [x] 后端: services/report_service.py (获取/生成/删除, 重新生成逻辑)
- [x] 后端: routers/reports.py
- [x] 前端: api/reports.ts
- [x] 前端: ReportPanel.tsx (报告选择器, 关注点生成, 状态展示)
- [x] PaperDetail.tsx集成ReportPanel

## Phase 9: 管理员后台
- [x] 后端: schemas/config.py, schemas/admin.py
- [x] 后端: routers/admin.py (统计/用户管理/配置CRUD)
- [x] 后端: routers/maintenance.py (维护模式开关)
- [x] 后端: routers/model_test.py (对话/嵌入/翻译连接测试)
- [x] 前端: api/admin.ts
- [x] 前端: admin/Dashboard.tsx, Users.tsx, Config.tsx
- [x] 前端: admin/Models.tsx, Maintenance.tsx, Password.tsx
- [x] 前端: admin/SharedPapers.tsx, Tasks.tsx
- [x] App.tsx所有admin路由替换为真实组件

## Phase 10: 实时通知系统
- [x] 后端: schemas/notification.py
- [x] 后端: services/notify_service.py (CRUD + 已读/未读)
- [x] 后端: routers/notify.py (REST接口 + WebSocket端点 + Redis pub/sub订阅)
- [x] 前端: api/notify.ts
- [x] 前端: stores/notifyStore.ts
- [x] 前端: hooks/useWebSocket.ts (自动重连, ping/pong)
- [x] 前端: NotificationButton.tsx (气泡通知列表)
- [x] Papers.tsx集成NotificationButton
