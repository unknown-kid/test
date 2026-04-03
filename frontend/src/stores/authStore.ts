import { create } from 'zustand'
import { authApi, type UserInfo } from '../api/auth'

let fetchUserPromise: Promise<void> | null = null

interface AuthState {
  user: UserInfo | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  adminLogin: (username: string, password: string) => Promise<void>
  register: (username: string, password: string) => Promise<string>
  logout: () => Promise<void>
  fetchUser: () => Promise<void>
  isLoggedIn: () => boolean
  isAdmin: () => boolean
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  loading: false,

  login: async (username, password) => {
    const res = await authApi.login(username, password)
    const { access_token, refresh_token, role } = res.data
    localStorage.setItem('access_token', access_token)
    localStorage.setItem('refresh_token', refresh_token)
    localStorage.setItem('role', role)
    await get().fetchUser()
  },

  adminLogin: async (username, password) => {
    const res = await authApi.adminLogin(username, password)
    const { access_token, refresh_token, role } = res.data
    localStorage.setItem('access_token', access_token)
    localStorage.setItem('refresh_token', refresh_token)
    localStorage.setItem('role', role)
    await get().fetchUser()
  },

  register: async (username, password) => {
    const res = await authApi.register(username, password)
    return res.data.message
  },

  logout: async () => {
    try {
      await authApi.logout()
    } catch { /* ignore */ }
    localStorage.clear()
    set({ user: null })
  },

  fetchUser: async () => {
    if (fetchUserPromise) {
      return fetchUserPromise
    }

    set({ loading: true })
    fetchUserPromise = (async () => {
      try {
        const res = await authApi.getMe()
        set({ user: res.data })
      } catch {
        set({ user: null })
      } finally {
        set({ loading: false })
        fetchUserPromise = null
      }
    })()

    return fetchUserPromise
  },

  isLoggedIn: () => !!get().user,
  isAdmin: () => get().user?.role === 'admin',
}))
