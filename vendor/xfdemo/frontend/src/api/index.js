import axios from 'axios'

// 创建 axios 实例
const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
  timeout: 120000, // 2分钟超时（AI分析需要时间）
  headers: {
    'Content-Type': 'application/json'
  }
})

// 响应拦截器
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const message = error.response?.data?.error || '服务器错误，请稍后重试'
    const requestError = new Error(message)
    requestError.status = error.response?.status
    return Promise.reject(requestError)
  }
)

/**
 * 健康检查
 * @returns {Promise<{status: string}>}
 */
export const checkHealth = () => {
  return api.get('/health')
}

export const registerAccount = (payload) => api.post('/auth/register', payload)

export const loginAccount = (payload) => api.post('/auth/login', payload)

export const logoutAccount = () => api.post('/auth/logout')

export const fetchCurrentUser = () => api.get('/auth/me')

/**
 * 消防安全检测
 * @param {Object} params
 * @param {string} params.query - 检测问题/描述
 * @param {string} [params.image] - 图片URL或Base64
 * @returns {Promise<{response: string, usage: Object}>}
 */
export const inspectFire = ({ query, image }) => {
  return api.post('/chat', { query, image })
}

/**
 * 流式消防安全检测
 * @param {Object} params
 * @param {string} params.query - 检测问题/描述
 * @param {string} [params.image] - 图片URL或Base64
 * @param {(delta: string) => void} [params.onChunk] - 流式文本回调
 * @param {(payload: {response: string, usage: Object}) => void} [params.onDone] - 完成回调
 * @param {AbortSignal} [params.signal] - 中断信号
 * @returns {Promise<{response: string, usage: Object}>}
 */
export const inspectFireStream = async ({ query, image, onChunk, onProgress, onDone, signal }) => {
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ query, image }),
    credentials: 'include',
    signal
  })

  if (!response.ok) {
    let message = '服务器错误，请稍后重试'

    try {
      const errorData = await response.json()
      message = errorData?.error || message
    } catch {
      // ignore parse error and use fallback message
    }

    throw new Error(message)
  }

  if (!response.body) {
    throw new Error('当前环境不支持流式响应')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let finalPayload = { response: '', usage: {}, yolo: null, trace: null, history: null }

  const handleLine = (line) => {
    if (!line.trim()) return

    const payload = JSON.parse(line)

    if (payload.type === 'delta') {
      const delta = payload.delta || ''
      finalPayload.response += delta
      onChunk?.(delta)
      return
    }

    if (payload.type === 'progress') {
      onProgress?.(payload)
      return
    }

    if (payload.type === 'done') {
      finalPayload = {
        response: payload.response ?? finalPayload.response,
        usage: payload.usage || {},
        yolo: payload.yolo || null,
        trace: payload.trace || null,
        history: payload.history || null
      }
      onDone?.(finalPayload)
      return
    }

    if (payload.type === 'error') {
      throw new Error(payload.error || '流式检测失败，请重试')
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })

    let lineBreakIndex = buffer.indexOf('\n')
    while (lineBreakIndex !== -1) {
      const line = buffer.slice(0, lineBreakIndex)
      buffer = buffer.slice(lineBreakIndex + 1)
      handleLine(line)
      lineBreakIndex = buffer.indexOf('\n')
    }

    if (done) {
      break
    }
  }

  if (buffer.trim()) {
    handleLine(buffer)
  }

  return finalPayload
}

/**
 * 将文件转换为 Base64
 * @param {File} file
 * @returns {Promise<string>}
 */
export const fileToBase64 = (file) => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}


const buildSearch = (params = {}) => {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, value)
    }
  })
  return search.toString()
}

const resolveMediaUrl = (value) => {
  if (!value || typeof value !== 'string') return ''
  try {
    return new URL(value, window.location.origin).href
  } catch {
    return value
  }
}

const normalizeRecordMedia = (payload) => ({
  ...payload,
  records: (payload?.records || []).map((record) => ({
    ...record,
    imageUrl: resolveMediaUrl(record.imageUrl),
    yoloImageUrl: resolveMediaUrl(record.yoloImageUrl),
    previewImageUrl: resolveMediaUrl(record.imageUrl)
  }))
})

export const fetchUltraStrictSamples = async (params = {}) => {
  const payload = await api.get(`/dataset/ultra-strict/samples?${buildSearch(params)}`)
  return normalizeRecordMedia(payload)
}

export const fetchInspectionHistory = async (params = {}) => {
  const payload = await api.get(`/history/inspections?${buildSearch(params)}`)
  return normalizeRecordMedia(payload)
}

export const deleteInspectionHistory = (id) => {
  return api.delete(`/history/inspections/${encodeURIComponent(id)}`)
}

export const clearInspectionHistory = () => {
  return api.delete(`/history/inspections`)
}

export const fetchInspectionReviews = (recordId) => {
  return api.get(`/history/inspections/${encodeURIComponent(recordId)}/reviews`)
}

export const createInspectionReview = (recordId, payload) => {
  return api.post(`/history/inspections/${encodeURIComponent(recordId)}/reviews`, payload)
}

export const deleteInspectionReview = (reviewId) => {
  return api.delete(`/history/reviews/${encodeURIComponent(reviewId)}`)
}

export const fetchInspectionRevisions = (recordId) => {
  return api.get(`/history/inspections/${encodeURIComponent(recordId)}/revisions`)
}

export const createInspectionRevision = (recordId, payload) => {
  return api.post(`/history/inspections/${encodeURIComponent(recordId)}/revisions`, payload)
}

export const checkPipesHealth = () => {
  return api.get('/pipes/health')
}

export const countPipes = ({ image, confidence, iou = 0.45, classes = [0, 1, 2, 3] }) => {
  return api.post('/pipes/count', {
    image,
    confidence,
    iou,
    classes,
    imageSize: 640,
    maxDetections: 2000
  })
}

export const fetchPipeHistory = async (limit = 12) => {
  const payload = await api.get(`/pipes/history?limit=${encodeURIComponent(limit)}`)
  return normalizeRecordMedia(payload)
}

export const deletePipeHistory = (id) => {
  return api.delete(`/pipes/history/${encodeURIComponent(id)}`)
}

export const clearPipeHistory = () => {
  return api.delete('/pipes/history')
}

export const fetchInspectionMonitor = async (params = {}) => {
  const payload = await api.get(`/monitor/inspection-stats?${buildSearch(params)}`)
  return normalizeRecordMedia({ ...payload, records: payload.recent || [] })
}

export default api
