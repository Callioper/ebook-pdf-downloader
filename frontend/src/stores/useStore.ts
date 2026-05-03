import { create } from 'zustand'
import axios from 'axios'
import { API_BASE } from '../constants'
import type { AppConfig, TaskItem, SearchParams, BookItem, BookCandidate } from '../types'

interface AppState {
  config: AppConfig | null
  tasks: TaskItem[]
  searchResults: BookItem[]
  externalBooks: BookCandidate[]
  searchTotal: number
  availableDbs: string[]
  loading: boolean
  error: string

  fetchConfig: () => Promise<void>
  updateConfig: (data: Partial<AppConfig>) => Promise<void>
  fetchTasks: () => Promise<void>
  fetchSearchResults: (params: SearchParams) => Promise<void>
  fetchAvailableDbs: () => Promise<void>
  setLoading: (v: boolean) => void
  setError: (e: string) => void
}

export const useStore = create<AppState>((set, get) => ({
  config: null,
  tasks: [],
  searchResults: [],
  externalBooks: [],
  searchTotal: 0,
  availableDbs: [],
  loading: false,
  error: '',

  fetchConfig: async () => {
    try {
      const { data } = await axios.get(`${API_BASE}/config`)
      set({ config: data })
    } catch (e: any) {
      set({ error: e.message })
    }
  },

  updateConfig: async (updates) => {
    try {
      const { data } = await axios.post(`${API_BASE}/config`, updates)
      set({ config: data })
    } catch (e: any) {
      set({ error: e.message })
    }
  },

  fetchTasks: async () => {
    try {
      const { data } = await axios.get(`${API_BASE}/tasks`)
      set({ tasks: data.tasks || [], error: '' })
    } catch (e: any) {
      set({ error: get().tasks.length === 0 ? e.message : '' })
    }
  },

  fetchSearchResults: async (params) => {
    set({ loading: true, error: '' })
    try {
      const queryParams: Record<string, any> = {}
      if (params.field) queryParams.field = params.field
      if (params.query) queryParams.query = params.query
      if (params.fuzzy !== undefined) queryParams.fuzzy = params.fuzzy
      if (params.fields) params.fields.forEach((f, i) => queryParams[`fields[]`] = params.fields?.[i] ?? '')
      if (params.queries) params.queries.forEach((q, i) => queryParams[`queries[]`] = params.queries?.[i] ?? '')
      if (params.logics) params.logics.forEach((l, i) => queryParams[`logics[]`] = params.logics?.[i] ?? '')
      if (params.fuzzies) params.fuzzies.forEach((f, i) => queryParams[`fuzzies[]`] = params.fuzzies?.[i] ?? '')
      if (params.page) queryParams.page = params.page
      if (params.page_size) queryParams.page_size = params.page_size

      const { data } = await axios.get(`${API_BASE}/search`, { params: queryParams })
      set({ searchResults: data.books || [], externalBooks: data.external_books || [], searchTotal: data.total || 0, loading: false })
    } catch (e: any) {
      set({ error: e.message, loading: false })
    }
  },

  fetchAvailableDbs: async () => {
    try {
      const { data } = await axios.get(`${API_BASE}/available-dbs`)
      set({ availableDbs: data.dbs || [] })
    } catch (e: any) {
      set({ error: e.message })
    }
  },

  setLoading: (v) => set({ loading: v }),
  setError: (e) => set({ error: e }),
}))
