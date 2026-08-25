import { useState } from 'react';
import { CalendarDays, Check, CheckSquare, MapPin, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { IconButton } from '@/components/ui/Button';
import { Card, SectionTitle } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { EmptyState, ErrorState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useCalendar, useDeleteTask, useTasks, useUpdateTask } from '@/hooks/queries';
import type { Task } from '@/types/api';
import { cn } from '@/utils/cn';

function TaskRow({
  task,
  onToggle,
  onDelete,
  busy,
}: {
  task: Task;
  onToggle: () => void;
  onDelete: () => void;
  busy: boolean;
}) {
  return (
    <li className="flex items-center gap-3 px-4 py-3">
      <button
        type="button"
        role="checkbox"
        aria-checked={task.completed}
        aria-label={`סימון "${task.title}" כהושלמה`}
        disabled={busy}
        onClick={onToggle}
        className={cn(
          'flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border-2 transition-colors',
          'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-bobi-600',
          task.completed
            ? 'border-emerald-500 bg-emerald-500 text-white'
            : 'border-slate-300 text-transparent hover:border-bobi-500 dark:border-slate-600',
        )}
      >
        <Check size={14} />
      </button>

      <div className="min-w-0 flex-1">
        <p
          className={cn(
            'text-sm font-medium',
            task.completed
              ? 'text-slate-400 line-through dark:text-slate-500'
              : 'text-slate-900 dark:text-slate-100',
          )}
        >
          {task.title}
        </p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-slate-500 dark:text-slate-400">
          <span>{task.owner}</span>
          <span aria-hidden="true">·</span>
          <span>{task.completed ? 'הושלמה' : (task.due_label ?? 'ללא תאריך')}</span>
          {task.created_by === 'בובי' ? <Badge tone="info">נוצר ע״י בובי</Badge> : null}
        </p>
      </div>

      <IconButton
        label={`מחיקת "${task.title}"`}
        icon={<Trash2 size={16} />}
        disabled={busy}
        className="text-rose-600 hover:bg-rose-50 dark:text-rose-400 dark:hover:bg-rose-500/10"
        onClick={onDelete}
      />
    </li>
  );
}

export function TasksPage() {
  const tasks = useTasks();
  const calendar = useCalendar();
  const update = useUpdateTask();
  const remove = useDeleteTask();
  const [showCompleted, setShowCompleted] = useState(false);

  const mutationError = update.error ?? remove.error;
  const busy = update.isPending || remove.isPending;

  return (
    <>
      <PageHeader
        title="משימות ויומן"
        description="מה פתוח, מה הושלם, ומה מתוכנן בימים הקרובים."
      />

      {mutationError ? (
        <div className="mb-4">
          <ErrorState error={mutationError} fallbackMessage="לא הצלחתי לעדכן את המשימה" />
        </div>
      ) : null}

      <div className="space-y-8">
        <section aria-labelledby="tasks-heading">
          <SectionTitle
            action={
              <button
                type="button"
                onClick={() => setShowCompleted((value) => !value)}
                className="text-sm text-bobi-700 hover:underline dark:text-bobi-300"
              >
                {showCompleted ? 'הסתרת שהושלמו' : 'הצגת שהושלמו'}
              </button>
            }
          >
            <span id="tasks-heading">המשימות שלי</span>
          </SectionTitle>

          <QueryBoundary
            isLoading={tasks.isLoading}
            error={tasks.error}
            data={tasks.data}
            errorMessage="לא הצלחתי לטעון את המשימות"
            onRetry={() => void tasks.refetch()}
            isEmpty={(data) => data.open_tasks.length === 0 && data.completed_tasks.length === 0}
            empty={
              <EmptyState
                title="אין משימות פתוחות 🎉"
                description="כשתוסיפו משימה לבובי היא תופיע כאן."
                icon={<CheckSquare size={32} />}
              />
            }
          >
            {(data) => (
              <div className="space-y-3">
                <Card className="p-0">
                  {data.open_tasks.length === 0 ? (
                    <div className="p-4">
                      <EmptyState title="אין משימות פתוחות 🎉" />
                    </div>
                  ) : (
                    <ul className="divide-y divide-slate-100 dark:divide-slate-700/60">
                      {data.open_tasks.map((task) => (
                        <TaskRow
                          key={task.id}
                          task={task}
                          busy={busy}
                          onToggle={() => update.mutate({ id: task.id, patch: { completed: true } })}
                          onDelete={() => remove.mutate(task.id)}
                        />
                      ))}
                    </ul>
                  )}
                </Card>

                {showCompleted && data.completed_tasks.length > 0 ? (
                  <Card className="p-0">
                    <p className="border-b border-slate-100 px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-400 dark:border-slate-700/60">
                      הושלמו
                    </p>
                    <ul className="divide-y divide-slate-100 dark:divide-slate-700/60">
                      {data.completed_tasks.map((task) => (
                        <TaskRow
                          key={task.id}
                          task={task}
                          busy={busy}
                          onToggle={() =>
                            update.mutate({ id: task.id, patch: { completed: false } })
                          }
                          onDelete={() => remove.mutate(task.id)}
                        />
                      ))}
                    </ul>
                  </Card>
                ) : null}
              </div>
            )}
          </QueryBoundary>
        </section>

        <section aria-labelledby="calendar-heading">
          <SectionTitle>
            <span id="calendar-heading">אירועים קרובים</span>
          </SectionTitle>

          <QueryBoundary
            isLoading={calendar.isLoading}
            error={calendar.error}
            data={calendar.data}
            errorMessage="לא הצלחתי לטעון את היומן"
            onRetry={() => void calendar.refetch()}
            isEmpty={(data) => data.events.length === 0}
            empty={
              <EmptyState
                title="אין אירועים קרובים"
                description="כשיהיו אירועים ביומן, בובי יזכיר לפניהם."
                icon={<CalendarDays size={32} />}
              />
            }
          >
            {(data) => (
              <Card className="p-0">
                <ul className="divide-y divide-slate-100 dark:divide-slate-700/60">
                  {data.events.map((event) => (
                    <li key={event.id} className="flex items-start gap-4 px-4 py-3">
                      <div className="w-20 shrink-0">
                        <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                          {event.day_label}
                        </p>
                        <p className="text-sm tabular-nums text-slate-500 dark:text-slate-400">
                          {event.time_label}
                        </p>
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="font-medium text-slate-900 dark:text-slate-100">
                          {event.title}
                        </p>
                        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-slate-500 dark:text-slate-400">
                          <span>{event.owner}</span>
                          {event.location ? (
                            <>
                              <span aria-hidden="true">·</span>
                              <span className="inline-flex items-center gap-1">
                                <MapPin aria-hidden="true" size={12} />
                                {event.location}
                              </span>
                            </>
                          ) : null}
                        </p>
                        {event.bobi_features.length > 0 ? (
                          <div className="mt-1.5 flex flex-wrap gap-1.5">
                            {event.bobi_features.map((feature) => (
                              <Badge key={feature} tone="info">
                                {feature}
                              </Badge>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </QueryBoundary>
        </section>
      </div>
    </>
  );
}
