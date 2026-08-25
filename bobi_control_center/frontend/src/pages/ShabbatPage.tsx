import { useEffect, useReducer, useState } from 'react';
import { Flame, Copy, Plus, RotateCcw, Save, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button, IconButton } from '@/components/ui/Button';
import { Card, SectionTitle } from '@/components/ui/Card';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { Modal } from '@/components/ui/Modal';
import { TextField, TimeField } from '@/components/ui/Field';
import { Toggle } from '@/components/ui/Toggle';
import { AdvancedDetails, AdvancedDisclosure } from '@/components/ui/Advanced';
import { PageHeader } from '@/components/ui/PageHeader';
import { EmptyState, ErrorState, QueryBoundary } from '@/components/state/QueryBoundary';
import {
  useConfirmShabbat,
  usePreviewShabbat,
  useSaveShabbatTemplate,
  useShabbat,
} from '@/hooks/queries';
import {
  countActiveRanges,
  draftReducer,
  toDraft,
  type DraftState,
} from '@/features/shabbat/draft';
import type { ChangePreview, ShabbatDeviceSchedule, TimeRange } from '@/types/api';
import { SHABBAT_DAY_LABELS } from '@/utils/format';
import { iconFor } from '@/utils/icons';

const INITIAL: DraftState = { schedules: [], dirty: false };

function RangeRow({
  range,
  onChange,
  onToggle,
  onRemove,
}: {
  range: TimeRange;
  onChange: (field: 'start' | 'end', value: string) => void;
  onToggle: () => void;
  onRemove: () => void;
}) {
  return (
    <li className="rounded-xl border border-slate-200 p-3 dark:border-slate-700">
      <div className="mb-2 flex items-center justify-between gap-2">
        <Badge tone="neutral">{SHABBAT_DAY_LABELS[range.day] ?? range.day}</Badge>
        <div className="flex items-center gap-2">
          <Toggle
            checked={range.enabled}
            onChange={onToggle}
            size="sm"
            label={`הפעלת הטווח ${range.start} עד ${range.end}`}
          />
          <IconButton
            label="מחיקת טווח"
            icon={<Trash2 size={15} />}
            className="text-rose-600 hover:bg-rose-50 dark:text-rose-400 dark:hover:bg-rose-500/10"
            onClick={onRemove}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <TimeField
          label="הדלקה"
          value={range.start}
          onChange={(event) => onChange('start', event.target.value)}
        />
        <TimeField
          label="כיבוי"
          value={range.end}
          onChange={(event) => onChange('end', event.target.value)}
        />
      </div>

      <p className="mt-2 flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
        {/* dir="ltr" keeps the arrow pointing from start to end; inside an RTL
            paragraph an un-isolated arrow points against the reading order. */}
        <span dir="ltr" className="tabular-nums">
          {range.start} → {range.end}
        </span>
        {/* Crossing midnight must be visible, not inferred by the reader. */}
        {range.crosses_midnight ? <Badge tone="info">+ יום הבא</Badge> : null}
      </p>
    </li>
  );
}

function ScheduleCard({
  schedule,
  dispatch,
}: {
  schedule: ShabbatDeviceSchedule;
  dispatch: React.Dispatch<Parameters<typeof draftReducer>[1]>;
}) {
  const Icon = iconFor(schedule.icon);

  return (
    <Card as="li" className="flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-bobi-50 text-bobi-600 dark:bg-bobi-500/15 dark:text-bobi-300"
        >
          <Icon size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-slate-900 dark:text-slate-100">
            {schedule.device_name}
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400">{schedule.room}</p>
        </div>
        <Toggle
          checked={schedule.enabled}
          onChange={() => dispatch({ type: 'toggleSchedule', scheduleId: schedule.id })}
          label={`הפעלת תזמון שבת עבור ${schedule.device_name}`}
        />
      </div>

      {schedule.note ? (
        <p className="text-xs text-slate-500 dark:text-slate-400">{schedule.note}</p>
      ) : null}

      {schedule.enabled ? (
        <>
          <ul className="space-y-2">
            {schedule.ranges.map((range) => (
              <RangeRow
                key={range.id}
                range={range}
                onChange={(field, value) =>
                  dispatch({
                    type: 'setRangeTime',
                    scheduleId: schedule.id,
                    rangeId: range.id,
                    field,
                    value,
                  })
                }
                onToggle={() =>
                  dispatch({ type: 'toggleRange', scheduleId: schedule.id, rangeId: range.id })
                }
                onRemove={() =>
                  dispatch({ type: 'removeRange', scheduleId: schedule.id, rangeId: range.id })
                }
              />
            ))}
          </ul>

          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => dispatch({ type: 'addRange', scheduleId: schedule.id, day: 'friday' })}
            >
              טווח בשישי
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() =>
                dispatch({ type: 'addRange', scheduleId: schedule.id, day: 'saturday' })
              }
            >
              טווח בשבת
            </Button>
          </div>
        </>
      ) : (
        <p className="rounded-xl bg-slate-50 p-3 text-sm text-slate-500 dark:bg-slate-900/40 dark:text-slate-400">
          המכשיר לא ייכלל בשבת הקרובה.
        </p>
      )}

      <AdvancedDisclosure>
        <AdvancedDetails advanced={schedule.advanced} />
      </AdvancedDisclosure>
    </Card>
  );
}

export function ShabbatPage() {
  const query = useShabbat();
  const previewMutation = usePreviewShabbat();
  const confirmMutation = useConfirmShabbat();
  const templateMutation = useSaveShabbatTemplate();

  const [state, dispatch] = useReducer(draftReducer, INITIAL);
  const [preview, setPreview] = useState<ChangePreview | null>(null);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [templateName, setTemplateName] = useState('');

  // Seed the draft from the saved configuration on first load and after a save.
  useEffect(() => {
    if (query.data) {
      dispatch({ type: 'reset', schedules: query.data.schedules });
    }
  }, [query.data]);

  const startSave = async () => {
    const result = await previewMutation.mutateAsync(
      toDraft(state, query.data?.active_template_id ?? null),
    );
    setPreview(result);
  };

  const commit = async () => {
    if (!preview) return;
    await confirmMutation.mutateAsync({
      draft: toDraft(state, query.data?.active_template_id ?? null),
      token: preview.token,
    });
    setPreview(null);
  };

  const saveTemplate = async () => {
    await templateMutation.mutateAsync([templateName, 'נשמר ממסך שעון שבת', state.schedules]);
    setTemplateOpen(false);
    setTemplateName('');
  };

  const mutationError = previewMutation.error ?? confirmMutation.error ?? templateMutation.error;

  return (
    <>
      <PageHeader
        title="שעון שבת"
        description="כל תזמוני השבת במקום אחד. שום שינוי לא נשמר עד שמאשרים."
      />

      {mutationError ? (
        <div className="mb-4">
          <ErrorState error={mutationError} fallbackMessage="הפעולה על שעון שבת נכשלה" />
        </div>
      ) : null}

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחתי לטעון את שעון השבת"
        onRetry={() => void query.refetch()}
      >
        {(config) => (
          <div className="space-y-6">
            <Card className="bg-gradient-to-bl from-bobi-50 to-white dark:from-bobi-500/10 dark:to-slate-800/60">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-medium text-bobi-700 dark:text-bobi-300">
                    {config.times.parasha}
                  </p>
                  <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                    {config.times.city}
                  </p>
                </div>
                <dl className="flex gap-6">
                  <div>
                    <dt className="text-xs text-slate-500 dark:text-slate-400">כניסת שבת</dt>
                    <dd className="text-xl font-bold tabular-nums text-slate-900 dark:text-slate-50">
                      {config.times.candle_lighting}
                    </dd>
                    <dd className="text-xs text-slate-400">{config.times.friday_date}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-slate-500 dark:text-slate-400">צאת שבת</dt>
                    <dd className="text-xl font-bold tabular-nums text-slate-900 dark:text-slate-50">
                      {config.times.havdalah}
                    </dd>
                    <dd className="text-xs text-slate-400">{config.times.saturday_date}</dd>
                  </div>
                </dl>
              </div>
            </Card>

            <section aria-labelledby="templates-heading">
              <SectionTitle>
                <span id="templates-heading">תבניות</span>
              </SectionTitle>
              <div className="flex flex-wrap gap-2">
                {config.templates.map((template) => (
                  <Button
                    key={template.id}
                    variant={template.id === config.active_template_id ? 'primary' : 'secondary'}
                    size="sm"
                    icon={<Copy size={14} />}
                    disabled={template.schedules.length === 0}
                    title={
                      template.schedules.length === 0
                        ? 'התבנית ריקה'
                        : template.description
                    }
                    onClick={() =>
                      dispatch({ type: 'loadTemplate', schedules: template.schedules })
                    }
                  >
                    {template.name}
                  </Button>
                ))}
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Save size={14} />}
                  onClick={() => setTemplateOpen(true)}
                >
                  שמירה כתבנית
                </Button>
              </div>
            </section>

            <section aria-labelledby="schedules-heading">
              <SectionTitle
                action={
                  <span className="text-sm text-slate-500 dark:text-slate-400">
                    {countActiveRanges(state.schedules)} טווחים פעילים
                  </span>
                }
              >
                <span id="schedules-heading">מכשירים</span>
              </SectionTitle>

              {state.schedules.length === 0 ? (
                <EmptyState
                  title="עדיין אין תזמוני שבת"
                  description="אפשר לטעון תבנית או להוסיף מכשירים."
                  icon={<Flame size={32} />}
                />
              ) : (
                <ul className="space-y-3">
                  {state.schedules.map((schedule) => (
                    <ScheduleCard key={schedule.id} schedule={schedule} dispatch={dispatch} />
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </QueryBoundary>

      {/* The save bar only appears once there is something to save. */}
      {state.dirty ? (
        <div className="fixed inset-x-0 bottom-16 z-20 border-t border-slate-200 bg-white/95 p-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] backdrop-blur lg:bottom-0 dark:border-slate-700 dark:bg-slate-900/95">
          <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-1">
            <p className="text-sm text-slate-600 dark:text-slate-300">יש שינויים שלא נשמרו</p>
            <div className="flex gap-2">
              <Button
                variant="ghost"
                icon={<RotateCcw size={16} />}
                onClick={() =>
                  dispatch({ type: 'reset', schedules: query.data?.schedules ?? [] })
                }
              >
                איפוס
              </Button>
              <Button
                icon={<Save size={16} />}
                loading={previewMutation.isPending}
                onClick={() => void startSave()}
              >
                תצוגה מקדימה
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      <ConfirmDialog
        open={preview !== null}
        preview={preview}
        title="שמירת תזמוני שבת"
        confirmLabel="שמירה"
        loading={confirmMutation.isPending}
        onConfirm={() => void commit()}
        onCancel={() => setPreview(null)}
      />

      <Modal
        open={templateOpen}
        onClose={() => setTemplateOpen(false)}
        title="שמירה כתבנית"
        description="התזמונים הנוכחיים יישמרו כדי שאפשר יהיה לטעון אותם בעתיד."
        footer={
          <>
            <Button variant="ghost" onClick={() => setTemplateOpen(false)}>
              ביטול
            </Button>
            <Button
              disabled={templateName.trim().length === 0}
              loading={templateMutation.isPending}
              onClick={() => void saveTemplate()}
            >
              שמירה
            </Button>
          </>
        }
      >
        <TextField
          label="שם התבנית"
          value={templateName}
          onChange={(event) => setTemplateName(event.target.value)}
          placeholder="לדוגמה: שבת עם אורחים"
        />
      </Modal>
    </>
  );
}
