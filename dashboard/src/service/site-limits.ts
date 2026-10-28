import { fetcher } from '@/service/http'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

export interface SiteLimit {
  id: number
  user_id: number
  name: string
  domains: string[]
  quota: number
  slow_speed: number
  used_traffic: number
  throttled: boolean
  expire_at: string | null
  reset_at: string
  created_at: string
}

export interface SiteLimitList {
  site_limits: SiteLimit[]
  timezone: string
  next_reset: string
}

export interface SiteLimitPreset {
  name: string
  domains: string[]
}

export interface SiteLimitCreate {
  name: string
  domains: string[]
  quota: number
  slow_speed: number
  days: number | null
}

export type SiteLimitModify = Partial<Omit<SiteLimitCreate, 'days'>> & { days?: number }

export const siteLimitsQueryKey = (userId: number) => [`/api/user/${userId}/site-limits`] as const

export const useSiteLimitPresets = (enabled: boolean) =>
  useQuery({
    queryKey: ['/api/site-limits/presets'],
    queryFn: () => fetcher<SiteLimitPreset[]>('/api/site-limits/presets'),
    enabled,
    staleTime: Infinity,
  })

export const useUserSiteLimits = (userId: number, enabled: boolean) =>
  useQuery({
    queryKey: siteLimitsQueryKey(userId),
    queryFn: () => fetcher<SiteLimitList>(`/api/user/${userId}/site-limits`),
    enabled: enabled && !!userId,
    refetchInterval: enabled ? 15_000 : false,
  })

const useSiteLimitMutation = <TVars>(userId: number, request: (vars: TVars) => Promise<unknown>) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: request,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: siteLimitsQueryKey(userId) }),
  })
}

export const useCreateSiteLimit = (userId: number) =>
  useSiteLimitMutation(userId, (body: SiteLimitCreate) => fetcher<SiteLimit>(`/api/user/${userId}/site-limits`, { method: 'POST', body }))

export const useModifySiteLimit = (userId: number) =>
  useSiteLimitMutation(userId, ({ id, body }: { id: number; body: SiteLimitModify }) =>
    fetcher<SiteLimit>(`/api/user/${userId}/site-limits/${id}`, { method: 'PUT', body }),
  )

export const useResetSiteLimit = (userId: number) =>
  useSiteLimitMutation(userId, (id: number) => fetcher<SiteLimit>(`/api/user/${userId}/site-limits/${id}/reset`, { method: 'POST' }))

export const useRemoveSiteLimit = (userId: number) =>
  useSiteLimitMutation(userId, (id: number) => fetcher(`/api/user/${userId}/site-limits/${id}`, { method: 'DELETE' }))
