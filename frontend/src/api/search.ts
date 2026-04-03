import client from './client'
import type { PaperInfo } from './files'

export interface PaperListResponse {
  items: PaperInfo[]
  total: number
  page: number
  page_size: number
}

export const searchApi = {
  keyword: (params: { keywords: string; folder_id?: string; zone?: string; page?: number; page_size?: number }) =>
    client.post<PaperListResponse>('/search/keyword', params),

  rag: (params: { query: string; folder_id?: string; zone?: string; page?: number; page_size?: number }) =>
    client.post<PaperListResponse>('/search/rag', params),

  cascade: (params: {
    keywords?: string; rag_query?: string; folder_id?: string;
    zone?: string; order?: string; page?: number; page_size?: number
  }) => client.post<PaperListResponse>('/search/cascade', params),
}
