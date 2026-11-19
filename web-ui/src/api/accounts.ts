import { http } from '@/lib/http'

export interface AccountItem {
  name: string
  path: string
}

export interface AccountDetail extends AccountItem {
  content: string
}

export interface AccountNode {
  name: string
  browser: string
  status: 'active' | 'available' | 'cooling' | 'pending' | 'missing' | 'invalid'
  selected_by: string[]
  running_by: string[]
  cooldown_until: number | null
  remaining_seconds: number
}

export interface AccountNodesSnapshot {
  updated_at: number
  nodes: AccountNode[]
}

export async function getAccountNodes(): Promise<AccountNodesSnapshot> {
  return await http('/api/accounts/nodes')
}

export async function listAccounts(): Promise<AccountItem[]> {
  return await http('/api/accounts')
}

export async function getAccount(name: string): Promise<AccountDetail> {
  return await http(`/api/accounts/${encodeURIComponent(name)}`)
}

export async function createAccount(payload: { name: string; content: string }): Promise<AccountDetail> {
  return await http('/api/accounts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function updateAccount(name: string, content: string): Promise<AccountDetail> {
  return await http(`/api/accounts/${encodeURIComponent(name)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
}

export async function deleteAccount(name: string): Promise<{ message: string }> {
  return await http(`/api/accounts/${encodeURIComponent(name)}`, { method: 'DELETE' })
}
