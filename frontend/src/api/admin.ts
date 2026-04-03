import client from './client'
import type { ReportInfo } from './reports'

export interface AdminStats {
  total_users: number
  pending_users: number
  total_papers: number
  shared_papers: number
  user_paper_counts: Array<{
    user_id: string
    username: string
    total_papers: number
    personal_papers: number
    failed_papers: number
  }>
}

export interface UserListItem {
  id: string
  username: string
  role: string
  status: string
  created_at: string
  last_login: string | null
}

export interface ConfigItem {
  key: string
  value: string
  description: string | null
  updated_at: string | null
}

export interface ModelTestRequest {
  model_type: string
  api_url: string
  api_key: string
  model_name: string
  translate_type?: string
}

export interface TaskBreakdownItem {
  task_name: string
  running: number
  reserved: number
  scheduled: number
}

export interface QueueOverview {
  waiting_count: number
  running_count: number
  reserved_count: number
  scheduled_count: number
  queued_total: number
  workers_online: number
  worker_nodes_target?: number
  worker_process_total?: number
  worker_total_limit?: number
  worker_total_in_use?: number
  worker_total_utilization_percent?: number | null
  inspect_error?: string | null
  task_breakdown: TaskBreakdownItem[]
}

export interface ModelConcurrencyItem {
  model_type: string
  model_name: string
  in_use: number
  limit: number
  utilization_percent: number | null
}

export interface StepStatusCounts {
  pending: number
  processing: number
  completed: number
  failed: number
}

export interface RunningPaperItem {
  paper_id: string
  title: string
  zone: string
  uploaded_by: string | null
  progress_percent: number
  completed_steps: number
  processing_steps: number
  failed_steps: number
  step_statuses: Record<string, string>
  created_at: string
}

export interface ModelUsageItem {
  model_type: string
  model_name: string
  requests_24h: number
  failed_24h: number
  success_rate_24h: number | null
}

export interface UserModelUsageItem extends ModelUsageItem {
  user_id: string
  username: string
}

export interface TopUserUsageItem {
  username: string
  requests_24h: number
  failed_24h: number
  model_count: number
}

export interface FailedTaskItem {
  id: string
  type: string
  content: string
  username: string | null
  created_at: string
}

export interface CleanupStuckTasksResult {
  message: string
  force_mode?: boolean
  queue_waiting_before_cleanup?: number
  running_before_cleanup?: number
  reserved_before_cleanup?: number
  scheduled_before_cleanup?: number
  runtime_cleanup?: {
    active_revoked: number
    reserved_revoked: number
    scheduled_revoked: number
    purged_waiting: number
    inspect_error?: string | null
  } | null
  scanned_papers?: number
  matched_papers: number
  failed_papers: number
  completed_fixed_papers: number
  failed_steps: number
  cleared_title_count?: number
  cleared_abstract_count?: number
  cleared_keywords_count?: number
  deleted_reports?: number
  deleted_chunk_rows?: number
  deleted_abstract_rows?: number
  vector_probe_error?: string | null
  vector_cleanup_error?: string | null
}

export interface TaskBoardOverview {
  generated_at: string
  queue: QueueOverview
  concurrency: {
    paper: {
      in_use: number
      limit: number
      utilization_percent: number | null
    }
    model_limit: number
    models: ModelConcurrencyItem[]
  }
  processing: {
    paper_status_counts: Record<string, number>
    step_status_counts: Record<string, StepStatusCounts>
    running_step_total: number
    failed_step_total: number
    completed_step_total: number
    overall_step_progress_percent: number
    running_papers_count: number
    running_papers_avg_progress_percent: number
    running_papers: RunningPaperItem[]
  }
  model_usage_24h: ModelUsageItem[]
  user_model_usage_24h: UserModelUsageItem[]
  top_users_24h: TopUserUsageItem[]
  recent_failed_tasks: FailedTaskItem[]
  artifact_audit: {
    generated_at?: string | null
    scanned_completed_papers: number
    queued_repairs: number
    embedding_configured: boolean
    completed_papers_with_any_gap: number
    completed_papers_missing_chunk_vectors: number
    completed_papers_missing_abstract_vectors: number
    completed_steps_missing_title: number
    completed_steps_missing_abstract: number
    completed_steps_missing_keywords: number
    completed_steps_missing_report: number
  }
}

export const adminApi = {
  getStats: () => client.get<AdminStats>('/admin/stats'),

  getUsers: (status?: string) =>
    client.get<UserListItem[]>('/admin/users', { params: status ? { status } : {} }),

  approveUser: (userId: string, action: string) =>
    client.post(`/admin/users/${userId}/approve`, { action }),

  removeUser: (userId: string) =>
    client.delete(`/admin/users/${userId}`),

  getConfigs: () => client.get<ConfigItem[]>('/admin/configs'),

  updateConfig: (key: string, value: string) =>
    client.put(`/admin/configs/${key}`, { value }),

  testModel: (req: ModelTestRequest) =>
    client.post<{ success: boolean; message: string }>('/admin/model-test/', req),

  getMaintenanceStatus: () =>
    client.get<{ maintenance: boolean }>('/admin/maintenance/status'),

  enableMaintenance: () =>
    client.post('/admin/maintenance/enable'),

  disableMaintenance: () =>
    client.post('/admin/maintenance/disable'),

  getPaperReports: (paperId: string) =>
    client.get<ReportInfo[]>(`/admin/papers/${paperId}/reports`),

  getTasksOverview: () =>
    client.get<TaskBoardOverview>('/admin/tasks/overview'),

  cleanupStuckProcessingTasks: (force = false) =>
    client.post<CleanupStuckTasksResult>('/admin/tasks/fail-stuck', undefined, {
      params: force ? { force: true } : undefined,
      timeout: 0,
    }),
}
