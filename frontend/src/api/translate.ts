import client from './client'

export interface TranslateResponse {
  original: string
  translated: string
}

export const translateApi = {
  translate: (text: string) =>
    client.post<TranslateResponse>('/translate/', { text, target_lang: 'zh' }),
}
