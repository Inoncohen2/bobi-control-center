import { Check, MessageCircle, Users, X } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card, SectionTitle } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { NextPhaseBadge, ReadOnlyNotice } from '@/components/ui/ReadOnly';
import { EmptyState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useUsers } from '@/hooks/queries';
import type { BridgeUser } from '@/types/api';
import { cn } from '@/utils/cn';

const PERMISSION_LABELS: Record<string, string> = {
  control_devices: 'שליטה במכשירים',
  manage_automations: 'ניהול אוטומציות',
  manage_shabbat: 'ניהול שעון שבת',
  manage_tasks: 'ניהול משימות',
  manage_calendar: 'ניהול יומן',
  view_cameras: 'צפייה במצלמות',
  manage_bobi: 'ניהול בובי',
};

const ROLE_LABELS: Record<string, string> = {
  admin: 'מנהל',
  member: 'בן/בת בית',
  guest: 'אורח',
};

function permissionLabel(permission: string): string {
  return PERMISSION_LABELS[permission] ?? permission.replace(/_/g, ' ');
}

/** Deterministic avatar colour so the same person keeps the same colour. */
function avatarColor(seed: string): string {
  const palette = ['#6366f1', '#ec4899', '#0ea5e9', '#f59e0b', '#10b981', '#8b5cf6'];
  let hash = 0;
  for (const char of seed) hash = (hash + char.charCodeAt(0)) % palette.length;
  return palette[hash] as string;
}

function UserCard({ user }: { user: BridgeUser }) {
  const role = (user.role ?? '').toLowerCase();

  return (
    <Card as="li">
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl text-lg font-semibold text-white"
          style={{ backgroundColor: avatarColor(user.id) }}
        >
          {user.name.charAt(0)}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold text-slate-900 dark:text-slate-100">{user.name}</h3>
            {user.role ? <Badge tone="neutral">{ROLE_LABELS[role] ?? user.role}</Badge> : null}
            <Badge tone={user.enabled === false ? 'muted' : 'ok'} dot>
              {user.enabled === false ? 'מושבת' : 'פעיל'}
            </Badge>
          </div>

          <dl className="mt-3 space-y-1.5 text-sm">
            {/* The bridge withholds phone numbers and LIDs, and so does this UI:
                only the connection status is ever shown. */}
            <div className="flex items-center gap-2">
              <MessageCircle aria-hidden="true" size={14} className="text-slate-400" />
              <dt className="sr-only">WhatsApp</dt>
              <dd className="text-slate-600 dark:text-slate-300">
                {user.whatsapp_connected ? 'מחובר ל-WhatsApp' : 'לא מחובר ל-WhatsApp'}
              </dd>
            </div>
            {user.calendar ? (
              <div className="flex items-center gap-2">
                <dt className="text-slate-400">יומן</dt>
                <dd className="text-slate-600 dark:text-slate-300">{user.calendar}</dd>
              </div>
            ) : null}
            {user.task_list ? (
              <div className="flex items-center gap-2">
                <dt className="text-slate-400">רשימת משימות</dt>
                <dd className="text-slate-600 dark:text-slate-300">{user.task_list}</dd>
              </div>
            ) : null}
            {user.areas.length > 0 ? (
              <div className="flex flex-wrap items-center gap-1.5 pt-1">
                <dt className="sr-only">חדרים</dt>
                {user.areas.map((area) => (
                  <dd key={area}>
                    <Badge tone="muted">{area}</Badge>
                  </dd>
                ))}
              </div>
            ) : null}
          </dl>
        </div>
      </div>
    </Card>
  );
}

export function UsersPage() {
  const query = useUsers();

  return (
    <>
      <PageHeader title="משתמשים" description="מי בבית, ומה כל אחד רשאי לעשות עם בובי." />

      <ReadOnlyNotice className="mb-4">
        פרופילים והרשאות מוצגים לקריאה בלבד. שינוי הרשאות יהיה זמין בשלב הבא.
      </ReadOnlyNotice>

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחתי לקבל את רשימת המשתמשים מ-Home Assistant"
        loadingLabel="טוען משתמשים…"
        onRetry={() => void query.refetch()}
        isEmpty={(data) => data.users.length === 0}
        empty={<EmptyState title="אין עדיין משתמשים" icon={<Users size={32} />} />}
      >
        {(data) => {
          // Build the permission axis from whatever the bridge actually sent,
          // so a new permission appears without a frontend change.
          const permissions = [
            ...new Set(data.users.flatMap((user) => user.permissions)),
          ].sort((a, b) => permissionLabel(a).localeCompare(permissionLabel(b), 'he'));

          return (
            <div className="space-y-8">
              <section aria-labelledby="profiles-heading">
                <SectionTitle>
                  <span id="profiles-heading">פרופילים</span>
                </SectionTitle>
                <ul className="grid gap-3 lg:grid-cols-2">
                  {data.users.map((user) => (
                    <UserCard key={user.id} user={user} />
                  ))}
                </ul>
              </section>

              {permissions.length > 0 ? (
                <section aria-labelledby="matrix-heading">
                  <SectionTitle action={<NextPhaseBadge />}>
                    <span id="matrix-heading">הרשאות</span>
                  </SectionTitle>
                  <Card className="overflow-x-auto p-0">
                    <table className="w-full min-w-[32rem] border-collapse text-sm">
                      <caption className="sr-only">
                        מטריצת הרשאות: לכל משתמש, אילו פעולות מותרות. לקריאה בלבד.
                      </caption>
                      <thead>
                        <tr className="border-b border-slate-200 dark:border-slate-700">
                          <th scope="col" className="p-3 text-right font-medium text-slate-500">
                            הרשאה
                          </th>
                          {data.users.map((user) => (
                            <th
                              key={user.id}
                              scope="col"
                              className="p-3 text-center font-medium text-slate-900 dark:text-slate-100"
                            >
                              {user.name}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {permissions.map((permission) => (
                          <tr
                            key={permission}
                            className="border-b border-slate-100 last:border-0 dark:border-slate-700/60"
                          >
                            <th
                              scope="row"
                              className="p-3 text-right font-normal text-slate-800 dark:text-slate-200"
                            >
                              {permissionLabel(permission)}
                            </th>
                            {data.users.map((user) => {
                              const granted = user.permissions.includes(permission);
                              return (
                                <td key={user.id} className="p-3 text-center">
                                  {/* Static, not a control: Phase 2 cannot write. */}
                                  <span
                                    role="img"
                                    aria-label={`${permissionLabel(permission)} עבור ${user.name}: ${
                                      granted ? 'מותר' : 'לא מותר'
                                    }`}
                                    className={cn(
                                      'inline-flex h-8 w-8 items-center justify-center rounded-lg',
                                      granted
                                        ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'
                                        : 'bg-slate-100 text-slate-400 dark:bg-slate-700 dark:text-slate-500',
                                    )}
                                  >
                                    {granted ? <Check size={16} /> : <X size={16} />}
                                  </span>
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </Card>
                </section>
              ) : null}
            </div>
          );
        }}
      </QueryBoundary>
    </>
  );
}
