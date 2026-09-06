import http from './http'

/** 认证相关接口封装。 */

export interface LoginResult {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface UserInfo {
  id: number
  username: string
  role: string
  is_active: boolean
  created_at: string
}

export function login(username: string, password: string) {
  return http.post<LoginResult>('/auth/login', { username, password })
}

export function register(username: string, password: string) {
  return http.post<UserInfo>('/auth/register', { username, password })
}

export function getMe() {
  return http.get<UserInfo>('/auth/me')
}

export function changePassword(old_password: string, new_password: string) {
  return http.put('/auth/password', { old_password, new_password })
}

export function logout(refresh_token: string) {
  return http.post('/auth/logout', { refresh_token })
}
