import { useEffect, useState } from 'react';
import { Check, MessageCircle, Moon, Save, Users, X } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, SectionTitle } from '@/components/ui/Card';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { PageHeader } from '@/components/ui/PageHeader';
import { EmptyState, ErrorState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useConfirmPermissions, usePreviewPermissions, useUsers } from '@/hooks/queries';
import type { ChangePreview, Permission, User } from '@/types/api';
import { cn } from '@/utils/cn';

function UserCard({ user }: { user: User }) {
  return (
    <Card as="li">
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl text-lg font-semibold text-white"
          style={{ backgroundColor: user.avatar_color }}
        >
          {user.name.charAt(0)}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold text-slate-900 dark:text-slate-100">{user.name}</h3>
            <Badge tone="neutral">{user.role_label}</Badge>
            <Badge tone={user.enabled ? 'ok' : 'muted'} dot>
              {user.enabled ? 'פעיל' : 'מושבת'}
            </Badge>
          </div>

          <dl className="mt-3 space-y-1.5 text-sm">
            <div className="flex items-center gap-2">
              <MessageCircle aria-hidden="true" size={14} className="text-slate-400" />
              <dt className="sr-only">WhatsApp</dt>
              <dd className="text-slate-600 dark:text-slate-300">
                {user.whatsapp_connected ? (
                  <>
                    מחובר <span dir="ltr">{user.whatsapp_hint}</span>
                  </>
                ) : (
                  'לא מחובר'
                )}
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
            <div className="flex items-center gap-2">
              <Moon aria-hidden="true" size={14} className="text-slate-400" />
              <dt className="sr-only">שעות שקטות</dt>
              <dd className="text-slate-600 dark:text-slate-300">
                {user.quiet_hours.enabled ? (
                  <span className="tabular-nums">
                    {user.quiet_hours.start}–{user.quiet_hours.end}
                  </span>
                ) : (
                  'ללא שעות שקטות'
                )}
              </dd>
            </div>
          </dl>
        </div>
      </div>
    </Card>
  );
}

export function UsersPage() {
  const query = useUsers();
  const previewMutation = usePreviewPermissions();
  const confirmMutation = useConfirmPermissions();

  /** Local draft of the permissions matrix, keyed by user id. */
  const [matrix, setMatrix] = useState<Record<string, Permission[]>>({});
  const [dirty, setDirty] = useState(false);
  const [pending, setPending] = useState<{
    userId: string;
    permissions: Permission[];
    preview: ChangePreview;
  } | null>(null);

  useEffect(() => {
    if (!query.data) return;
    const next: Record<string, Permission[]> = {};
    for (const user of query.data.users) next[user.id] = [...user.permissions];
    setMatrix(next);
    setDirty(false);
  }, [query.data]);

  const togglePermission = (userId: string, permission: Permission) => {
    setMatrix((current) => {
      const existing = current[userId] ?? [];
      const next = existing.includes(permission)
        ? existing.filter((item) => item !== permission)
        : [...existing, permission];
      return { ...current, [userId]: next };
    });
    setDirty(true);
  };

  const startSave = async (userId: string) => {
    const permissions = matrix[userId] ?? [];
    const preview = await previewMutation.mutateAsync({ userId, permissions });
    setPending({ userId, permissions, preview });
  };

  const commit = async () => {
    if (!pending) return;
    await confirmMutation.mutateAsync({
      userId: pending.userId,
      permissions: pending.permissions,
      token: pending.preview.token,
    });
    setPending(null);
    setDirty(false);
  };

  const mutationError = previewMutation.error ?? confirmMutation.error;

  return (
    <>
      <PageHeader title="משתמשים" description="מי בבית, ומה כל אחד רשאי לעשות עם בובי." />

      {mutationError ? (
        <div className="mb-4">
          <ErrorState error={mutationError} fallbackMessage="לא הצלחתי לעדכן את ההרשאות" />
        </div>
      ) : null}

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחתי לטעון את המשתמשים"
        onRetry={() => void query.refetch()}
        isEmpty={(data) => data.users.length === 0}
        empty={
          <EmptyState title="אין עדיין משתמשים" icon={<Users size={32} />} />
        }
      >
        {(data) => (
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

            <section aria-labelledby="matrix-heading">
              <SectionTitle>
                <span id="matrix-heading">הרשאות</span>
              </SectionTitle>
              <Card className="overflow-x-auto p-0">
                <table className="w-full min-w-[36rem] border-collapse text-sm">
                  <caption className="sr-only">
                    מטריצת הרשאות: לכל משתמש, אילו פעולות מותרות
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
                    {data.permissions.map((permission) => (
                      <tr
                        key={permission.id}
                        className="border-b border-slate-100 last:border-0 dark:border-slate-700/60"
                      >
                        <th scope="row" className="p-3 text-right font-normal">
                          <span className="font-medium text-slate-800 dark:text-slate-200">
                            {permission.label}
                          </span>
                          <span className="mt-0.5 block text-xs text-slate-400">
                            {permission.description}
                          </span>
                        </th>
                        {data.users.map((user) => {
                          const granted = (matrix[user.id] ?? []).includes(permission.id);
                          return (
                            <td key={user.id} className="p-3 text-center">
                              <button
                                type="button"
                                role="checkbox"
                                aria-checked={granted}
                                aria-label={`${permission.label} עבור ${user.name}`}
                                onClick={() => togglePermission(user.id, permission.id)}
                                className={cn(
                                  'inline-flex h-8 w-8 items-center justify-center rounded-lg transition-colors',
                                  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-bobi-600',
                                  granted
                                    ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'
                                    : 'bg-slate-100 text-slate-400 dark:bg-slate-700 dark:text-slate-500',
                                )}
                              >
                                {granted ? <Check size={16} /> : <X size={16} />}
                              </button>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>

              {dirty ? (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <p className="text-sm text-slate-600 dark:text-slate-300">
                    יש שינויי הרשאות שלא נשמרו. שינוי הרשאות דורש אישור.
                  </p>
                  {data.users.map((user) => (
                    <Button
                      key={user.id}
                      variant="secondary"
                      size="sm"
                      icon={<Save size={14} />}
                      loading={previewMutation.isPending}
                      onClick={() => void startSave(user.id)}
                    >
                      שמירה עבור {user.name}
                    </Button>
                  ))}
                </div>
              ) : null}
            </section>
          </div>
        )}
      </QueryBoundary>

      <ConfirmDialog
        open={pending !== null}
        preview={pending?.preview ?? null}
        title="שינוי הרשאות"
        confirmLabel="עדכון הרשאות"
        loading={confirmMutation.isPending}
        onConfirm={() => void commit()}
        onCancel={() => setPending(null)}
      />
    </>
  );
}
