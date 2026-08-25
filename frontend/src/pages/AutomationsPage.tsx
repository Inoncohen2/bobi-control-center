import { useState } from 'react';
import { Copy, Pencil, Plus, Power, Timer, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button, IconButton } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { AdvancedDetails, AdvancedDisclosure } from '@/components/ui/Advanced';
import { PageHeader } from '@/components/ui/PageHeader';
import { EmptyState, ErrorState, QueryBoundary } from '@/components/state/QueryBoundary';
import {
  useAutomations,
  useConfirmDeleteAutomation,
  useDuplicateAutomation,
  usePreviewDeleteAutomation,
  useToggleAutomation,
} from '@/hooks/queries';
import { AutomationWizard } from '@/features/automations/AutomationWizard';
import { draftFromAutomation, emptyDraft } from '@/features/automations/wizard';
import type { Automation, AutomationDraft, ChangePreview } from '@/types/api';
import { AUTOMATION_TYPE_LABELS, formatDays, timeAgo } from '@/utils/format';

function TimeSummary({ automation }: { automation: Automation }) {
  if (automation.times.length > 0) {
    return <span className="tabular-nums">{automation.times.join(' · ')}</span>;
  }
  if (automation.start_time && automation.end_time) {
    return (
      <span className="inline-flex items-center gap-1.5">
        {/* See ShabbatPage: the arrow needs an isolated LTR run in RTL text. */}
        <span dir="ltr" className="tabular-nums">
          {automation.start_time} → {automation.end_time}
        </span>
        {/* The flag is computed server-side; the UI only renders it. */}
        {automation.crosses_midnight ? <Badge tone="info">+ יום הבא</Badge> : null}
      </span>
    );
  }
  if (automation.start_time) {
    return <span className="tabular-nums">{automation.start_time}</span>;
  }
  return <span>ללא שעה קבועה</span>;
}

function AutomationCard({
  automation,
  onEdit,
  onDelete,
  onDuplicate,
  onToggle,
  busy,
}: {
  automation: Automation;
  onEdit: () => void;
  onDelete: () => void;
  onDuplicate: () => void;
  onToggle: (enabled: boolean) => void;
  busy: boolean;
}) {
  return (
    <Card as="li" className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-semibold text-slate-900 dark:text-slate-100">{automation.name}</h3>
          <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{automation.summary}</p>
        </div>
        <Badge tone={automation.enabled ? 'ok' : 'muted'} dot>
          {automation.enabled ? 'פעיל' : 'מושבת'}
        </Badge>
      </div>

      <dl className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate-600 dark:text-slate-300">
        <div className="flex items-center gap-1.5">
          <dt className="sr-only">ימים</dt>
          <dd>{formatDays(automation.days) || 'לפי תאריך'}</dd>
        </div>
        <div className="flex items-center gap-1.5">
          <dt className="sr-only">שעות</dt>
          <dd>
            <TimeSummary automation={automation} />
          </dd>
        </div>
        <Badge tone="neutral">{AUTOMATION_TYPE_LABELS[automation.automation_type]}</Badge>
      </dl>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3 dark:border-slate-700/60">
        <span className="text-xs text-slate-400 dark:text-slate-500">
          הופעל לאחרונה {timeAgo(automation.last_triggered)}
        </span>
        <div className="flex items-center gap-1">
          <IconButton
            label={`עריכת ${automation.name}`}
            icon={<Pencil size={16} />}
            onClick={onEdit}
          />
          <IconButton
            label={`${automation.enabled ? 'השבתת' : 'הפעלת'} ${automation.name}`}
            icon={<Power size={16} />}
            disabled={busy}
            onClick={() => onToggle(!automation.enabled)}
          />
          <IconButton
            label={`שכפול ${automation.name}`}
            icon={<Copy size={16} />}
            disabled={busy}
            onClick={onDuplicate}
          />
          <IconButton
            label={`מחיקת ${automation.name}`}
            icon={<Trash2 size={16} />}
            variant="ghost"
            className="text-rose-600 hover:bg-rose-50 dark:text-rose-400 dark:hover:bg-rose-500/10"
            onClick={onDelete}
          />
        </div>
      </div>

      <AdvancedDisclosure>
        <AdvancedDetails advanced={automation.advanced} />
      </AdvancedDisclosure>
    </Card>
  );
}

export function AutomationsPage() {
  const query = useAutomations();
  const toggle = useToggleAutomation();
  const duplicate = useDuplicateAutomation();
  const previewDelete = usePreviewDeleteAutomation();
  const confirmDelete = useConfirmDeleteAutomation();

  const [wizardDraft, setWizardDraft] = useState<AutomationDraft | null>(null);
  const [pendingDelete, setPendingDelete] = useState<{
    id: string;
    preview: ChangePreview;
  } | null>(null);

  const startDelete = async (automation: Automation) => {
    const preview = await previewDelete.mutateAsync(automation.id);
    setPendingDelete({ id: automation.id, preview });
  };

  const runDelete = async () => {
    if (!pendingDelete) return;
    await confirmDelete.mutateAsync({
      id: pendingDelete.id,
      token: pendingDelete.preview.token,
    });
    setPendingDelete(null);
  };

  const mutationError = toggle.error ?? duplicate.error ?? previewDelete.error;

  return (
    <>
      <PageHeader
        title="אוטומציות"
        description="כל התזמונים והכללים של בובי במקום אחד."
        action={
          <Button icon={<Plus size={16} />} onClick={() => setWizardDraft(emptyDraft())}>
            אוטומציה חדשה
          </Button>
        }
      />

      {mutationError ? (
        <div className="mb-4">
          <ErrorState error={mutationError} fallbackMessage="הפעולה על האוטומציה נכשלה" />
        </div>
      ) : null}

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחתי לטעון את האוטומציות"
        onRetry={() => void query.refetch()}
        isEmpty={(data) => data.automations.length === 0}
        empty={
          <EmptyState
            title="אין כרגע אוטומציות"
            description="אפשר ליצור את הראשונה ולראות תצוגה מקדימה לפני שמירה."
            icon={<Timer size={32} />}
            action={
              <Button icon={<Plus size={16} />} onClick={() => setWizardDraft(emptyDraft())}>
                אוטומציה חדשה
              </Button>
            }
          />
        }
      >
        {(data) => (
          <ul className="space-y-3">
            {data.automations.map((automation) => (
              <AutomationCard
                key={automation.id}
                automation={automation}
                busy={toggle.isPending || duplicate.isPending}
                onEdit={() => setWizardDraft(draftFromAutomation(automation))}
                onDuplicate={() => duplicate.mutate(automation.id)}
                onToggle={(enabled) => toggle.mutate({ id: automation.id, enabled })}
                onDelete={() => void startDelete(automation)}
              />
            ))}
          </ul>
        )}
      </QueryBoundary>

      {wizardDraft ? (
        <AutomationWizard
          initial={wizardDraft}
          onClose={() => setWizardDraft(null)}
          onSaved={() => setWizardDraft(null)}
        />
      ) : null}

      <ConfirmDialog
        open={pendingDelete !== null}
        preview={pendingDelete?.preview ?? null}
        title="מחיקת אוטומציה"
        confirmLabel="מחיקה"
        loading={confirmDelete.isPending}
        onConfirm={() => void runDelete()}
        onCancel={() => setPendingDelete(null)}
      />
    </>
  );
}
