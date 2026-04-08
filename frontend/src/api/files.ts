import client from './client'

export interface FolderInfo {
  id: string
  name: string
  parent_id: string | null
  zone: string
  owner_id: string | null
  depth: number
  paper_count: number
  created_at: string
}

export interface PaperInfo {
  id: string
  title: string | null
  abstract: string | null
  keywords: string[] | null
  similarity_score?: number | null
  file_size: number
  folder_id: string | null
  processing_status: string
  step_statuses: Record<string, string>
  zone: string
  original_filename: string | null
  created_at: string
}

export interface FolderContentResponse {
  folders: FolderInfo[]
  papers: {
    items: PaperInfo[]
    total: number
    page: number
    page_size: number
  }
  current_folder: { id: string; name: string } | null
  breadcrumbs: { id: string; name: string }[]
}

export interface FolderTreeNode {
  id: string
  name: string
  children: FolderTreeNode[]
  paper_count: number
}

export const filesApi = {
  getContents: (params: { folder_id?: string; zone?: string; page?: number; page_size?: number }) =>
    client.get<FolderContentResponse>('/files/contents', { params }),

  getFolderTree: (zone: string) =>
    client.get<FolderTreeNode[]>('/files/folders/tree', { params: { zone } }),

  createFolder: (name: string, zone: string, parent_id?: string) =>
    client.post<FolderInfo>('/files/folders', { name, parent_id }, { params: { zone } }),

  renameFolder: (folderId: string, name: string) =>
    client.put<FolderInfo>(`/files/folders/${folderId}/rename`, { name }),

  deleteFolder: (folderId: string) =>
    client.delete(`/files/folders/${folderId}`),

  uploadPaper: (file: File, zone: string, folder_id?: string) => {
    const formData = new FormData()
    formData.append('file', file)
    return client.post<PaperInfo>('/papers/upload', formData, {
      params: { zone, folder_id },
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0,
    })
  },

  uploadPapersBatch: (files: File[], zone: string, folder_id?: string) => {
    const formData = new FormData()
    files.forEach((f) => formData.append('files', f))
    return client.post('/papers/upload/batch', formData, {
      params: { zone, folder_id },
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0,
    })
  },

  uploadPapersByUrl: (urls: string[], zone: string, folder_id?: string) =>
    client.post('/papers/upload/by-url', { urls }, {
      params: { zone, folder_id },
      timeout: 0,
    }),

  getPaper: (paperId: string) =>
    client.get<PaperInfo>(`/papers/${paperId}`),

  updatePaperKeywords: (paperId: string, keywords: string[]) =>
    client.put<PaperInfo>(`/papers/${paperId}/keywords`, { keywords }),

  deletePaper: (paperId: string) =>
    client.delete(`/papers/${paperId}`),

  batchDeletePapers: (paperIds: string[]) =>
    client.post('/papers/batch/delete', paperIds),

  batchMovePapers: (paperIds: string[], targetFolderId: string | null) =>
    client.post('/papers/batch/move', { paper_ids: paperIds, target_folder_id: targetFolderId }),

  batchCopyPapers: (paperIds: string[], targetFolderId: string | null) =>
    client.post('/papers/batch/copy', { paper_ids: paperIds, target_folder_id: targetFolderId }),

  reprocessPapers: (
    zone: 'personal' | 'shared',
    folderId?: string,
    failedOnly: boolean = false,
  ) =>
    client.post('/papers/reprocess', null, {
      params: {
        zone,
        folder_id: folderId,
        failed_only: failedOnly,
      },
    }),

  movePaper: (paperId: string, targetFolderId: string | null) =>
    client.put<PaperInfo>(`/papers/${paperId}/move`, { target_folder_id: targetFolderId }),

  copyPaper: (paperId: string, targetFolderId: string | null) =>
    client.post(`/papers/${paperId}/copy`, { target_folder_id: targetFolderId }),
}
