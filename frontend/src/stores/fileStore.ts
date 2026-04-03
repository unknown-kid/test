import { create } from 'zustand'
import { filesApi, type FolderContentResponse, type FolderTreeNode } from '../api/files'

interface FileState {
  zone: 'personal' | 'shared'
  currentFolderId: string | null
  contents: FolderContentResponse | null
  folderTree: FolderTreeNode[]
  loading: boolean
  page: number
  pageSize: number
  setZone: (zone: 'personal' | 'shared') => void
  setCurrentFolder: (folderId: string | null) => void
  setPage: (page: number) => void
  setPageSize: (size: number) => void
  fetchContents: () => Promise<void>
  fetchTree: () => Promise<void>
}

export const useFileStore = create<FileState>((set, get) => ({
  zone: 'personal',
  currentFolderId: null,
  contents: null,
  folderTree: [],
  loading: false,
  page: 1,
  pageSize: 20,

  setZone: (zone) => set({ zone, currentFolderId: null, page: 1 }),
  setCurrentFolder: (folderId) => set({ currentFolderId: folderId, page: 1 }),
  setPage: (page) => set({ page }),
  setPageSize: (size) => set({ pageSize: size, page: 1 }),

  fetchContents: async () => {
    const { zone, currentFolderId, page, pageSize } = get()
    set({ loading: true })
    try {
      const res = await filesApi.getContents({
        folder_id: currentFolderId || undefined,
        zone,
        page,
        page_size: pageSize,
      })
      set({ contents: res.data })
    } catch {
      set({ contents: null })
    } finally {
      set({ loading: false })
    }
  },

  fetchTree: async () => {
    const { zone } = get()
    try {
      const res = await filesApi.getFolderTree(zone)
      set({ folderTree: res.data })
    } catch {
      set({ folderTree: [] })
    }
  },
}))
