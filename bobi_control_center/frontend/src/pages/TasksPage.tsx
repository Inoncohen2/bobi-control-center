import { useState } from 'react';
import { Check, CheckSquare, Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button, IconButton } from '@/components/ui/Button';
import { Card, SectionTitle } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { SelectField, TextField } from '@/components/ui/Field';
import { Modal } from '@/components/ui/Modal';
import { EmptyState, QueryBoundary } from '@/components/state/QueryBoundary';
import { ChangeDialog } from '@/features/manage/ChangeDialog';
import { useManagedChange } from '@/features/manage/useManagedChange';
import { ManagementNotice, useResource } from '@/features/manage/ManagementNotice';
import { keys, useManagementStatus, useTasks } from '@/hooks/queries';
import type { BridgeTask } from '@/types/api';
import { formatDate } from '@/utils/format';
import { cn } from '@/utils/cn';

interface RowActions {
  /** Undefined while management is unavailable — the row then renders read-only. */
  onEdit?: (task: BridgeTask) => void;
  onToggle?: (task: BridgeTask) => void;
  onDelete?: (task: BridgeTask) => void;
}

function TaskRow({ task, actions }: { task: BridgeTask; actions: RowActions }) {
  const done = task.completed;
  const canManage = Boolean(actions.onToggle);

  return (
    <li className="flex items-center gap-3 px-4 py-3">
      {/*
        Completing a task is a change like any other: it opens the preview
        dialog rather than toggling in place. While management is unavailable
        this is a plain indicator, exactly as it was in Phase 2.
      */}
      {canManage ? (
        <button
          type="button"
          aria-label={done ? 'החזרת המשימה לפעילה' : 'סימון המשימה כבוצעה'}
          onClick={() => actions.onToggle?.(task)}
          className={cn(
            'flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border-2 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-bobi-600',
            done
              ? 'border-emerald-500 bg-emerald-500 text-white'
              : 'border-slate-300 text-transparent hover:border-bobi-500 dark:border-slate-600',
          )}
        >
          <Check size={14} />
        </button>
      ) : (
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
      )}

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

      {canManage ? (
        <div className="flex shrink-0 items-center gap-1">
          {done ? (
            <IconButton
              label="החזרה לפעילה"
              icon={<RotateCcw size={16} />}
              onClick={() => actions.onToggle?.(task)}
            />
          ) : null}
          <IconButton
            label="שינוי שם"
            icon={<Pencil size={16} />}
            onClick={() => actions.onEdit?.(task)}
          />
          <IconButton
            label="מחיקה"
            icon={<Trash2 size={16} />}
            onClick={() => actions.onDelete?.(task)}
          />
        </div>
      ) : null}
    </li>
  );
}

/** The add/rename form. Submitting only asks for a preview — it never saves. */
function TaskForm({
  open,
  task,
  owners,
  onClose,
  onPreview,
}: {
  open: boolean;
  task: BridgeTask | null;
  owners: string[];
  onClose: () => void;
  onPreview: (values: { title: string; owner: string }) => void;
}) {
  const [title, setTitle] = useState('');
  const [owner, setOwner] = useState('');

  // Re-seed whenever the dialog opens on a different task.
  const seed = task?.id ?? 'new';
  const [seeded, setSeeded] = useState(seed);
  if (open && seeded !== seed) {
    setSeeded(seed);
    setTitle(task?.title ?? '');
    setOwner(task?.owner ?? owners[0] ?? '');
  }

  if (!open) return null;

  return (
    <Modal
      open
      onClose={onClose}
      title={task ? 'שינוי שם משימה' : 'הוספת משימה'}
      description="אחרי המילוי תוצג תצוגה מקדימה לפני כל שינוי."
      footer={
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={!title.trim()}
            onClick={() => onPreview({ title: title.trim(), owner })}
          >
            המשך לתצוגה מקדימה
          </Button>
          <Button variant="secondary" onClick={onClose}>
            ביטול
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <TextField
          id="task-title"
          label="תוכן המשימה"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="לקבוע תור לרופא"
        />
        {task ? null : (
          <SelectField
            id="task-owner"
            label="למי המשימה שייכת"
            value={owner}
            onChange={(event) => setOwner(event.target.value)}
            options={owners.map((name) => ({ value: name, label: name }))}
          />
        )}
      </div>
    </Modal>
  );
}

export function TasksPage() {
  const query = useTasks();
  const management = useManagementStatus();
  const tasksResource = useResource(management.data, 'tasks');
  const change = useManagedChange('tasks', [keys.tasks]);

  const [showCompleted, setShowCompleted] = useState(false);
  const [form, setForm] = useState<{ open: boolean; task: BridgeTask | null }>({
    open: false,
    task: null,
  });

  const canManage = tasksResource?.available ?? false;

  const supports = (operation: string) =>
    canManage && (tasksResource?.operations ?? []).some((item) => item.id === operation);

  const actions: RowActions = canManage
    ? {
        onEdit: (task) => setForm({ open: true, task }),
        onToggle: (task) => {
          const operation = task.completed ? 'reopen' : 'complete';
          if (!supports(operation)) return;
          void change.start({
            operation,
            resource_id: task.id,
            payload: { owner: task.owner, current_title: task.title },
          });
        },
        onDelete: (task) =>
          void change.start({
            operation: 'delete',
            resource_id: task.id,
            payload: { owner: task.owner, current_title: task.title },
          }),
      }
    : {};

  return (
    <>
      <PageHeader title="משימות" description="המשימות שבובי מנהל עבור בני הבית." />

      <ManagementNotice
        status={management.data}
        resource="tasks"
        className="mb-4"
        readOnlyText="המשימות מוצגות לקריאה בלבד. סימון והוספה יהיו זמינים כשהניהול יופעל ב-Home Assistant."
      />

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחתי לקבל את רשימת המשימות מ-Home Assistant"
        loadingLabel="טוען משימות…"
        onRetry={() => void query.refetch()}
        isEmpty={(data) => data.tasks.length === 0 && !canManage}
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
                <SectionTitle
                  action={
                    supports('create') ? (
                      <Button
                        size="sm"
                        icon={<Plus size={16} />}
                        onClick={() => setForm({ open: true, task: null })}
                      >
                        משימה חדשה
                      </Button>
                    ) : null
                  }
                >
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
                        <TaskRow key={task.id} task={task} actions={actions} />
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
                          <TaskRow key={task.id} task={task} actions={actions} />
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

      <TaskForm
        open={form.open}
        task={form.task}
        owners={query.data?.owners ?? []}
        onClose={() => setForm({ open: false, task: null })}
        onPreview={({ title, owner }) => {
          const task = form.task;
          setForm({ open: false, task: null });
          void change.start(
            task
              ? {
                  operation: 'rename',
                  resource_id: task.id,
                  payload: { title, owner: task.owner, current_title: task.title },
                }
              : { operation: 'create', payload: { title, owner } },
          );
        }}
      />

      <ChangeDialog change={change} />
    </>
  );
}
