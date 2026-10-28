import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import useDirDetection from '@/hooks/use-dir-detection'
import {
  type SiteLimit,
  type SiteLimitCreate,
  useCreateSiteLimit,
  useModifySiteLimit,
  useRemoveSiteLimit,
  useResetSiteLimit,
  useSiteLimitPresets,
  useUserSiteLimits,
} from '@/service/site-limits'
import { dateUtils } from '@/utils/dateFormatter'
import { formatBytes } from '@/utils/formatByte'
import { Gauge, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

interface UserSiteLimitsModalProps {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  userId: number
  username?: string
}

const GB = 1024 ** 3
const SPEED_UNITS = { kbps: 1000 / 8, mbps: 1_000_000 / 8 } as const
type SpeedUnit = keyof typeof SPEED_UNITS
// "0" keeps the limit and resets it every day; other values remove it at 00:00 after that many days.
const DURATIONS = ['1', '7', '30', '0'] as const

interface FormState {
  id: number | null
  preset: string
  name: string
  domains: string
  quotaGb: string
  speed: string
  speedUnit: SpeedUnit
  days: string
}

const emptyForm: FormState = { id: null, preset: '', name: '', domains: '', quotaGb: '1', speed: '1', speedUnit: 'mbps', days: '1' }

const formatSpeed = (bytesPerSecond: number) => {
  const kbps = (bytesPerSecond * 8) / 1000
  return kbps >= 1000 ? `${+(kbps / 1000).toFixed(2)} Mbps` : `${+kbps.toFixed(0)} Kbps`
}

const formFromLimit = (limit: SiteLimit): FormState => {
  const useMbps = limit.slow_speed >= SPEED_UNITS.mbps
  return {
    id: limit.id,
    preset: '',
    name: limit.name,
    domains: limit.domains.join('\n'),
    quotaGb: String(+(limit.quota / GB).toFixed(3)),
    speed: String(+(limit.slow_speed / SPEED_UNITS[useMbps ? 'mbps' : 'kbps']).toFixed(2)),
    speedUnit: useMbps ? 'mbps' : 'kbps',
    days: '',
  }
}

const errorDetail = (error: any) => {
  const detail = error?.data?.detail
  if (Array.isArray(detail)) return detail.map((d: any) => d?.msg).join(', ')
  return (typeof detail === 'string' && detail) || error?.message || ''
}

export function UserSiteLimitsModal({ isOpen, onOpenChange, userId, username }: UserSiteLimitsModalProps) {
  const { t } = useTranslation()
  const dir = useDirDetection()
  const [form, setForm] = useState<FormState | null>(null)
  const [limitToDelete, setLimitToDelete] = useState<SiteLimit | null>(null)

  const { data, isLoading, error } = useUserSiteLimits(userId, isOpen)
  const { data: presets } = useSiteLimitPresets(isOpen)
  const createMutation = useCreateSiteLimit(userId)
  const modifyMutation = useModifySiteLimit(userId)
  const resetMutation = useResetSiteLimit(userId)
  const removeMutation = useRemoveSiteLimit(userId)

  const limits = data?.site_limits || []
  const saving = createMutation.isPending || modifyMutation.isPending

  const update = (patch: Partial<FormState>) => setForm(prev => (prev ? { ...prev, ...patch } : prev))

  const applyPreset = (name: string) => {
    const preset = presets?.find(p => p.name === name)
    if (preset) update({ preset: name, name: preset.name, domains: preset.domains.join('\n') })
  }

  const submit = () => {
    if (!form) return
    const domains = form.domains
      .split(/[\n,]/)
      .map(d => d.trim())
      .filter(Boolean)
    const quota = Math.round(parseFloat(form.quotaGb) * GB)
    const slowSpeed = Math.round(parseFloat(form.speed) * SPEED_UNITS[form.speedUnit])
    if (!form.name.trim() || domains.length === 0 || !(quota >= 0) || !(slowSpeed >= 1024)) {
      toast.error(t('siteLimits.invalid', { defaultValue: 'Fill in a name, at least one domain, a quota and a slow speed of at least 9 Kbps' }))
      return
    }
    const body: SiteLimitCreate = { name: form.name.trim(), domains, quota, slow_speed: slowSpeed, days: form.days === '0' ? null : Number(form.days || 1) }
    const onSuccess = () => {
      toast.success(t('siteLimits.saved', { defaultValue: 'Site limit saved' }))
      setForm(null)
    }
    const onError = (e: any) => toast.error(t('siteLimits.saveFailed', { defaultValue: 'Failed to save site limit' }), { description: errorDetail(e) })

    if (form.id === null) {
      createMutation.mutate(body, { onSuccess, onError })
    } else {
      const { days, ...rest } = body
      modifyMutation.mutate({ id: form.id, body: form.days === '' ? rest : { ...rest, days: days ?? 0 } }, { onSuccess, onError })
    }
  }

  const durationLabel = (value: string) =>
    ({
      '1': t('siteLimits.todayOnly', { defaultValue: 'Today only (removed at 00:00)' }),
      '7': t('siteLimits.days', { count: 7, defaultValue: '{{count}} days' }),
      '30': t('siteLimits.days', { count: 30, defaultValue: '{{count}} days' }),
      '0': t('siteLimits.always', { defaultValue: 'Always (resets every 00:00)' }),
    })[value]

  const renderForm = () => {
    if (!form) return null
    return (
      <div className="bg-muted/40 space-y-3 rounded-md border p-3">
        {presets && presets.length > 0 && (
          <div className="space-y-1">
            <Label>{t('siteLimits.preset', { defaultValue: 'Preset' })}</Label>
            <Select value={form.preset} onValueChange={applyPreset}>
              <SelectTrigger>
                <SelectValue placeholder={t('siteLimits.choosePreset', { defaultValue: 'Choose a site…' })} />
              </SelectTrigger>
              <SelectContent>
                {presets.map(p => (
                  <SelectItem key={p.name} value={p.name}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
        <div className="space-y-1">
          <Label>{t('siteLimits.name', { defaultValue: 'Name' })}</Label>
          <Input value={form.name} maxLength={64} onChange={e => update({ name: e.target.value })} />
        </div>
        <div className="space-y-1">
          <Label>{t('siteLimits.domains', { defaultValue: 'Domains (one per line)' })}</Label>
          <Textarea dir="ltr" rows={5} className="font-mono text-xs" placeholder="instagram.com&#10;cdninstagram.com" value={form.domains} onChange={e => update({ domains: e.target.value })} />
          <p className="text-muted-foreground text-xs">
            {t('siteLimits.domainsHint', { defaultValue: 'A domain also covers its subdomains. Xray matchers like full:, keyword:, regexp: and geosite: work too.' })}
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <Label>{t('siteLimits.quota', { defaultValue: 'Full-speed quota per day (GB)' })}</Label>
            <Input type="number" min={0} step="0.1" dir="ltr" value={form.quotaGb} onChange={e => update({ quotaGb: e.target.value })} />
          </div>
          <div className="space-y-1">
            <Label>{t('siteLimits.slowSpeed', { defaultValue: 'Speed after the quota' })}</Label>
            <div className="flex gap-2">
              <Input type="number" min={0} step="0.1" dir="ltr" value={form.speed} onChange={e => update({ speed: e.target.value })} />
              <Select value={form.speedUnit} onValueChange={v => update({ speedUnit: v as SpeedUnit })}>
                <SelectTrigger className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="kbps">Kbps</SelectItem>
                  <SelectItem value="mbps">Mbps</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
        <div className="space-y-1">
          <Label>{t('siteLimits.duration', { defaultValue: 'Active for' })}</Label>
          <Select value={form.days} onValueChange={v => update({ days: v })}>
            <SelectTrigger>
              <SelectValue placeholder={t('siteLimits.keepDuration', { defaultValue: 'Keep current' })} />
            </SelectTrigger>
            <SelectContent>
              {DURATIONS.map(d => (
                <SelectItem key={d} value={d}>
                  {durationLabel(d)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => setForm(null)} disabled={saving}>
            {t('cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button type="button" onClick={submit} disabled={saving}>
            {t('save', { defaultValue: 'Save' })}
          </Button>
        </div>
      </div>
    )
  }

  const renderLimit = (limit: SiteLimit) => {
    const percent = limit.quota > 0 ? Math.min(100, (limit.used_traffic / limit.quota) * 100) : 100
    return (
      <div key={limit.id} className="bg-card space-y-2 rounded-md border p-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{limit.name}</span>
              {limit.throttled ? (
                <Badge variant="destructive">{t('siteLimits.throttled', { defaultValue: 'Slowed' })}</Badge>
              ) : (
                <Badge variant="secondary">{t('siteLimits.fullSpeed', { defaultValue: 'Full speed' })}</Badge>
              )}
            </div>
            <p className="text-muted-foreground truncate font-mono text-xs" dir="ltr" title={limit.domains.join('\n')}>
              {limit.domains.map(d => d.replace(/^domain:/, '')).join(', ')}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <Button type="button" variant="ghost" size="icon" className="h-8 w-8" title={t('siteLimits.reset', { defaultValue: 'Reset today' })} disabled={resetMutation.isPending} onClick={() => resetMutation.mutate(limit.id, { onError: e => toast.error(errorDetail(e)) })}>
              <RefreshCw className="h-4 w-4" />
            </Button>
            <Button type="button" variant="ghost" size="icon" className="h-8 w-8" onClick={() => setForm(formFromLimit(limit))}>
              <Pencil className="h-4 w-4" />
            </Button>
            <Button type="button" variant="ghost" size="icon" className="text-destructive hover:text-destructive h-8 w-8" onClick={() => setLimitToDelete(limit)}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
        <Progress value={percent} indicatorClassName={limit.throttled ? 'bg-destructive' : undefined} />
        <div className="text-muted-foreground flex flex-wrap justify-between gap-x-4 gap-y-1 text-xs">
          <span dir="ltr">
            {formatBytes(limit.used_traffic)} / {formatBytes(limit.quota)}
          </span>
          <span>
            {t('siteLimits.then', { defaultValue: 'then' })} <span dir="ltr">{formatSpeed(limit.slow_speed)}</span>
          </span>
          <span>
            {limit.expire_at
              ? `${t('siteLimits.removedAt', { defaultValue: 'Removed at' })} ${dateUtils.toDayjs(limit.expire_at).format('YYYY-MM-DD HH:mm')}`
              : t('siteLimits.always', { defaultValue: 'Always (resets every 00:00)' })}
          </span>
        </div>
      </div>
    )
  }

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[90vh] max-w-full flex-col sm:h-[680px] sm:max-w-2xl" dir={dir}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Gauge className="h-5 w-5" />
            <span>{t('siteLimits.title', { defaultValue: 'Site limits' })}</span>
            {username && (
              <Badge variant="outline" dir="ltr">
                {username}
              </Badge>
            )}
          </DialogTitle>
          <DialogDescription>
            {t('siteLimits.description', { defaultValue: 'Full speed for these sites until the daily quota is used, then the slow speed. Usage resets every day at 00:00.' })}
            {data && (
              <span className="block text-xs" dir="ltr">
                {data.timezone} · {t('siteLimits.nextReset', { defaultValue: 'next reset' })} {dateUtils.toDayjs(data.next_reset).format('YYYY-MM-DD HH:mm')}
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        {!form && (
          <div className="flex justify-end">
            <Button type="button" className="flex items-center gap-2" onClick={() => setForm({ ...emptyForm })}>
              <Plus className="h-4 w-4" />
              <span>{t('siteLimits.add', { defaultValue: 'Add site limit' })}</span>
            </Button>
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-hidden">
          <div className="h-full overflow-y-auto">
            <div className="space-y-3 p-1">
              {renderForm()}
              {isLoading && Array.from({ length: 2 }).map((_, i) => <Skeleton key={i} className="h-24 w-full" />)}
              {error && <div className="text-destructive py-8 text-center text-sm">{t('siteLimits.loadFailed', { defaultValue: 'Failed to load site limits' })}</div>}
              {!isLoading && !error && limits.length === 0 && !form && (
                <div className="text-muted-foreground flex h-40 flex-col items-center justify-center gap-2 text-center">
                  <Gauge className="h-8 w-8" />
                  <p className="text-sm">{t('siteLimits.empty', { defaultValue: 'No site limits for this user' })}</p>
                </div>
              )}
              {limits.map(renderLimit)}
            </div>
          </div>
        </div>

        <div className="flex justify-end border-t pt-3">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t('close', { defaultValue: 'Close' })}
          </Button>
        </div>
      </DialogContent>

      <AlertDialog open={!!limitToDelete} onOpenChange={open => !open && setLimitToDelete(null)}>
        <AlertDialogContent dir={dir}>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('siteLimits.deleteTitle', { defaultValue: 'Remove site limit' })}</AlertDialogTitle>
            <AlertDialogDescription>{limitToDelete?.name}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={removeMutation.isPending}>{t('cancel', { defaultValue: 'Cancel' })}</AlertDialogCancel>
            <AlertDialogAction
              disabled={removeMutation.isPending}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() =>
                limitToDelete &&
                removeMutation.mutate(limitToDelete.id, {
                  onSuccess: () => setLimitToDelete(null),
                  onError: e => toast.error(errorDetail(e)),
                })
              }
            >
              {t('remove', { defaultValue: 'Remove' })}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Dialog>
  )
}
