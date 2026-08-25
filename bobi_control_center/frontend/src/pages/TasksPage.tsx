import { useState } from 'react';
import { Check, CheckSquare } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card, SectionTitle } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { NextPhaseBadge, ReadOnlyNotice } from '@/components/ui/ReadOnly';
import { EmptyState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useTasks } from '@/hooks/queries';
import type { BridgeTask } from '@/types/api';
import { formatDate } from '@/utils/format';
import { cn } from '@/utils/cn';

function TaskRow({ task }: { task: BridgeTask }) {
  const done = task.completed;

  return (
    <li className="flex items-center gap-3 px-4 py-3">
      {/* A static indicator, not a checkbox: completing a task is a write. */}
      <span
        role="img"
        aria-label={done ? 'הושלמה' : 'פתוחה'}
        className={cn(
          'flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border-2',
          done
            ? 'border-emerald-500 bg-emerald-500 text-white'
            : 'border-slate-300 text-transparent dark:border-slate-600',
        )}
      >
        <Check size={14} />
      </span>

      <div className="min-w-0 flex-1">
        <p
          className={cn(
            'text-sm font-medium',
            done
              ? 'text-slate-400 line-through dark:text-slate-500'
              : 'text-slate-900 dark:text-slate-100',
          )}
        >
          {task.title}
        </p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-slate-500 dark:text-slate-400">
          {task.owner ? <span>{task.owner}</span> : null}
          {task.owner && (task.due || task.list_name) ? <span aria-hidden="true">·</span> : null}
          {task.due ? <span>{formatDate(task.due)}</span> : null}
          {task.list_name ? <Badge tone="muted">{task.list_name}</Badge> : null}
        </p>
      </div>
    </li>
  );
}

export function TasksPage() {
  const query = useTasks();
  const [showCompleted, setShowCompleted] = useState(false);

  return (
    <>
      <PageHeader title="משימות" description="המשימות שבובי מנהל עבור בני הבית." />

      <ReadOnlyNotice className="mb-4">
        המשימות מוצגות לקריאה בלבד. סימון והוספה יהיו זמינים בשלב הבא.
      </ReadOnlyNotice>

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחתי לקבל את רשימת המשימות מ-Home Assistant"
        loadingLabel="טוען משימות…"
        onRetry={() => void query.refetch()}
        isEmpty={(data) => data.tasks.length === 0}
        empty={
          <EmptyState
            title="אין משימות פתוחות 🎉"
            description="כשתוסיפו משימה לבובי היא תופיע כאן."
            icon={<CheckSquare size={32} />}
          />
        }
      >
        {(data) => {
          const open = data.tasks.filter((task) => !task.completed);
          const completed = data.tasks.filter((task) => task.completed);

          return (
            <div className="space-y-6">
              <section aria-labelledby="open-heading">
                <SectionTitle action={<NextPhaseBadge />}>
                  <span id="open-heading">משימות פתוחות</span>
                </SectionTitle>
                <Card className="p-0">
                  {open.length === 0 ? (
                    <div className="p-4">
                      <EmptyState title="אין משימות פתוחות 🎉" />
                    </div>
                  ) : (
                    <ul className="divide-y divide-slate-100 dark:divide-slate-700/60">
                      {open.map((task) => (
                        <TaskRow key={task.id} task={task} />
                      ))}
                    </ul>
                  )}
                </Card>
              </section>

              {completed.length > 0 ? (
                <section aria-labelledby="completed-heading">
                  <SectionTitle
                    action={
                      <button
                        type="button"
                        onClick={() => setShowCompleted((value) => !value)}
                        className="text-sm text-bobi-700 hover:underline dark:text-bobi-300"
                      >
                        {showCompleted ? 'הסתרה' : `הצגה (${completed.length})`}
                      </button>
                    }
                  >
                    <span id="completed-heading">הושלמו</span>
                  </SectionTitle>
                  {showCompleted ? (
                    <Card className="p-0">
                      <ul className="divide-y divide-slate-100 dark:divide-slate-700/60">
                        {completed.map((task) => (
                          <TaskRow key={task.id} task={task} />
                        ))}
                      </ul>
                    </Card>
                  ) : null}
                </section>
              ) : null}
            </div>
          );
        }}
      </QueryBoundary>
    </>
  );
}
