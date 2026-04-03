import client from './client'

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  role: string
}

export interface UserInfo {
  id: string
  username: string
  role: string
  status: string
  created_at: string
  last_login: string | null
  custom_chat_api_url: string | null
  custom_chat_model_name: string | null
}

export const authApi = {
  login: (username: string, password: string) =>
    client.post<TokenResponse>('/auth/login', { username, password }),

  adminLogin: (username: string, password: string) =>
    client.post<TokenResponse>('/auth/admin/login', { username, password }),

  register: (username: string, password: string) =>
    client.post<{ message: string; user_id: string }>('/auth/register', { username, password }),

  refresh: (refresh_token: string) =>
    client.post<TokenResponse>('/auth/refresh', { refresh_token }),

  logout: () => client.post('/auth/logout'),

  getMe: () => client.get<UserInfo>('/auth/me'),

  changeAdminPassword: (old_password: string, new_password: string) =>
    client.put('/auth/admin/password', { old_password, new_password }),
}
