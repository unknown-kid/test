import client from './client'

export interface ReportInfo {
  id: string
  paper_id: string
  user_id: string | null
  report_type: string
  content: string | null
  focus_points: string | null
  status: string
  created_at: string
}

export const reportsApi = {
  getReports: (paperId: string) =>
    client.get<ReportInfo[]>(`/reports/${paperId}`),

  generateReport: (paperId: string, focusPoints?: string) =>
    client.post<ReportInfo>(`/reports/${paperId}/generate`, { focus_points: focusPoints }),

  deleteReport: (reportId: string) =>
    client.delete(`/reports/${reportId}`),
}
