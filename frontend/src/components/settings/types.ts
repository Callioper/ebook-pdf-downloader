import { AppConfig } from '../../types'

export interface SectionProps {
  form: AppConfig
  updateForm: (data: Partial<AppConfig>) => void
  mountedRef: React.MutableRefObject<boolean>
}
