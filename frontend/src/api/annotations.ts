import client from './client'

export interface HighlightInfo {
  id: string
  paper_id: string
  user_id: string
  page: number
  position_data: Record<string, any>
  created_at: string
}

export interface AnnotationInfo {
  id: string
  paper_id: string
  user_id: string
  page: number
  position_data: Record<string, any>
  content: string
  created_at: string
}

export interface NoteInfo {
  id: string
  paper_id: string
  user_id: string
  content: string
  created_at: string
  updated_at: string
}

export const annotationsApi = {
  getHighlights: (paperId: string) =>
    client.get<HighlightInfo[]>(`/annotations/highlights/${paperId}`),

  createHighlight: (data: { paper_id: string; page: number; position_data: Record<string, any> }) =>
    client.post<HighlightInfo>('/annotations/highlights', data),

  deleteHighlight: (id: string) =>
    client.delete(`/annotations/highlights/${id}`),

  getAnnotations: (paperId: string) =>
    client.get<AnnotationInfo[]>(`/annotations/annotations/${paperId}`),

  createAnnotation: (data: { paper_id: string; page: number; position_data: Record<string, any>; content: string }) =>
    client.post<AnnotationInfo>('/annotations/annotations', data),

  deleteAnnotation: (id: string) =>
    client.delete(`/annotations/annotations/${id}`),

  getNote: (paperId: string) =>
    client.get<NoteInfo | null>(`/annotations/notes/${paperId}`),

  updateNote: (paperId: string, content: string) =>
    client.put<NoteInfo>(`/annotations/notes/${paperId}`, { content }),
}
