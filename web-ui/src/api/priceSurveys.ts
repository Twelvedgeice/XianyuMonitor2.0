import { http } from '@/lib/http'

export interface SurveySettings { task_id: number | null; keyword: string; item_limit: number }
export interface SurveyRun {
  id: string; keyword: string; item_limit: number; state: string; started_at: string;
  kind?: string; target_count?: number;
  finished_at: string | null; actual_count: number; pages: number; account: string | null; error: string | null;
  summary: { priced_count?: number; min?: number | null; max?: number | null; median?: number | null;
    mean?: number | null; missing_count?: number; coverage?: string; stage?: string;
    sold_count?: number; available_count?: number; unavailable_count?: number;
    unknown_count?: number; failed_count?: number; pending_count?: number }
}
export interface SurveyItem {
  keyword: string; item_id: string; title: string; link: string; price: number | null;
  price_display: string; last_seen: string; status: string; sold_price: number | null; sold_at: string | null
  sold_source?: string | null; history_source?: string | null; last_checked?: string | null;
  check_status?: string | null; check_source?: string | null; check_evidence?: string | null; checked_price?: number | null
}
export interface SurveyItems { items: SurveyItem[]; total: number; page: number; limit: number; keywords: string[]; history_counts?: Record<string,number> }
export const getSurveyState = (): Promise<{ settings: SurveySettings; latest: SurveyRun | null }> => http('/api/price-surveys/state')
function send(path: string, method: string, value?: unknown) {
  return http('/api/price-surveys'+path, { method, headers: { 'Content-Type':'application/json' }, body: JSON.stringify(value) })
}
export const saveSurveySettings = (value: SurveySettings) => send('/settings','PUT',value)
export const startSurvey = (value: SurveySettings): Promise<SurveyRun> => send('/runs','POST',value)
export const cancelSurvey = () => send('/cancel','POST')
export const markSurveySold = (item: SurveyItem, sold: boolean, sold_price: number | null) =>
  send('/items/sold','PATCH',{keyword:item.keyword,item_id:item.item_id,sold,sold_price})
export const getSurveyItems = (keyword: string,q: string,status: string,page: number): Promise<SurveyItems> =>
  http('/api/price-surveys/items?'+new URLSearchParams({keyword,q,status,page:String(page)}))
