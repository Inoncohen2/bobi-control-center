import { useState } from 'react';
import { Check, ChevronLeft, ChevronRight } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Chip, SelectField, TextField, TimeField } from '@/components/ui/Field';
import { Modal } from '@/components/ui/Modal';
import { ErrorState } from '@/components/state/QueryBoundary';
import { useConfirmAutomation, useDevices, usePreviewAutomation } from '@/hooks/queries';
import type { AutomationDraft, ChangePreview } from '@/types/api';
import { HEBREW_DAYS_SHORT } from '@/utils/format';
import { cn } from '@/utils/cn';
import {
  ACTION_OPTIONS,
  STEP_LABELS,
  TYPE_OPTIONS,
  canAdvance,
  stepsFor,
  targetFromDevice,
  type StepId,
} from './wizard';

interface WizardProps {
  initial: AutomationDraft;
  onClose: () => void;
  onSaved: () => void;
}

function StepDots({ steps, current }: { steps: StepId[]; current: number }) {
  return (
    <ol className="mb-5 flex items-center gap-1.5" aria-label="שלבי האשף">
      {steps.map((step, index) => (
        <li key={step} className="flex flex-1 items-center gap-1.5">
          <span
            aria-current={index === current ? 'step' : undefined}
            className={cn(
              'h-1.5 flex-1 rounded-full transition-colors',
              index <= current ? 'bg-bobi-600' : 'bg-slate-200 dark:bg-slate-700',
            )}
          />
        </li>
      ))}
    </ol>
  );
}

export function AutomationWizard({ initial, onClose, onSaved }: WizardProps) {
  const [draft, setDraft] = useState<AutomationDraft>(initial);
  const [stepIndex, setStepIndex] = useState(0);
  const [preview, setPreview] = useState<ChangePreview | null>(null);

  const devices = useDevices();
  const previewMutation = usePreviewAutomation();
  const confirmMutation = useConfirmAutomation();

  const steps = stepsFor(draft.automation_type);
  const step = steps[Math.min(stepIndex, steps.length - 1)] as StepId;
  const isLast = step === 'summary';

  const update = (patch: Partial<AutomationDraft>) =>
    setDraft((current) => ({ ...current, ...patch }));

  const goNext = async () => {
    if (isLast) return;
    const nextStep = steps[stepIndex + 1];
    // Entering the summary step is what fetches the server-built preview.
    if (nextStep === 'summary') {
      const result = await previewMutation.mutateAsync(draft);
      setPreview(result);
    }
    setStepIndex((index) => index + 1);
  };

  const save = async () => {
    if (!preview) return;
    await confirmMutation.mutateAsync({ draft, token: preview.token });
    onSaved();
  };

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={draft.id ? 'עריכת אוטומציה' : 'אוטומציה חדשה'}
      description={STEP_LABELS[step]}
      footer={
        <>
          <Button
            variant="ghost"
            icon={<ChevronRight size={16} />}
            disabled={stepIndex === 0 || confirmMutation.isPending}
            onClick={() => setStepIndex((index) => Math.max(0, index - 1))}
          >
            הקודם
          </Button>
          {isLast ? (
            <Button
              icon={<Check size={16} />}
              loading={confirmMutation.isPending}
              onClick={() => void save()}
            >
              שמירה
            </Button>
          ) : (
            <Button
              icon={<ChevronLeft size={16} />}
              disabled={!canAdvance(draft, step)}
              loading={previewMutation.isPending}
              onClick={() => void goNext()}
            >
              הבא
            </Button>
          )}
        </>
      }
    >
      <StepDots steps={steps} current={stepIndex} />

      {step === 'action' ? (
        <div className="space-y-4">
          <TextField
            label="שם האוטומציה"
            value={draft.name}
            onChange={(event) => update({ name: event.target.value })}
            placeholder="לדוגמה: אור מטבח בערב"
          />
          <div>
            <p className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-300">
              מה לעשות?
            </p>
            <div className="flex flex-wrap gap-2">
              {ACTION_OPTIONS.map((option) => (
                <Chip
                  key={option.type}
                  selected={draft.actions[0]?.type === option.type}
                  onClick={() =>
                    update({ actions: [{ type: option.type, label: option.label, value: null }] })
                  }
                >
                  {option.label}
                </Chip>
              ))}
            </div>
          </div>
          <SelectField
            label="סוג התזמון"
            value={draft.automation_type}
            onChange={(event) => {
              update({ automation_type: event.target.value as AutomationDraft['automation_type'] });
              setStepIndex(0);
            }}
            options={TYPE_OPTIONS.map((option) => ({
              value: option.value,
              label: option.label,
            }))}
            help={TYPE_OPTIONS.find((option) => option.value === draft.automation_type)?.help}
          />
        </div>
      ) : null}

      {step === 'target' ? (
        <div>
          <p className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-300">
            על אילו מכשירים?
          </p>
          <div className="max-h-80 space-y-1.5 overflow-y-auto">
            {(devices.data?.devices ?? []).map((device) => {
              const selected = draft.targets.some((target) => target.id === device.id);
              return (
                <label
                  key={device.id}
                  className="flex cursor-pointer items-center gap-3 rounded-xl border border-slate-200 p-2.5 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-700/40"
                >
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() =>
                      update({
                        targets: selected
                          ? draft.targets.filter((target) => target.id !== device.id)
                          : [...draft.targets, targetFromDevice(device)],
                      })
                    }
                    className="h-4 w-4 rounded border-slate-300 text-bobi-600 focus:ring-bobi-500"
                  />
                  <span className="flex-1 text-sm text-slate-800 dark:text-slate-200">
                    {device.display_name}
                  </span>
                  <span className="text-xs text-slate-400">{device.room}</span>
                </label>
              );
            })}
          </div>
        </div>
      ) : null}

      {step === 'time' ? (
        <div className="space-y-4">
          {draft.automation_type === 'multi_time' ? (
            <div>
              <p className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-300">שעות</p>
              <div className="space-y-2">
                {draft.times.map((time, index) => (
                  <div key={index} className="flex gap-2">
                    <TimeField
                      label={`שעה ${index + 1}`}
                      className="flex-1"
                      value={time}
                      onChange={(event) => {
                        const next = [...draft.times];
                        next[index] = event.target.value;
                        update({ times: next });
                      }}
                    />
                    <Button
                      variant="ghost"
                      size="sm"
                      className="self-end"
                      onClick={() =>
                        update({ times: draft.times.filter((_, i) => i !== index) })
                      }
                    >
                      הסרה
                    </Button>
                  </div>
                ))}
              </div>
              <Button
                variant="secondary"
                size="sm"
                className="mt-2"
                onClick={() => update({ times: [...draft.times, '08:00'] })}
              >
                הוספת שעה
              </Button>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              <TimeField
                label={draft.automation_type === 'time_window' ? 'שעת התחלה' : 'שעה'}
                value={draft.start_time ?? ''}
                onChange={(event) => update({ start_time: event.target.value })}
              />
              {draft.automation_type === 'time_window' ? (
                <TimeField
                  label="שעת סיום"
                  value={draft.end_time ?? ''}
                  onChange={(event) => update({ end_time: event.target.value })}
                  help="אם שעת הסיום מוקדמת מההתחלה, בובי ימשיך אל היום הבא."
                />
              ) : null}
            </div>
          )}
        </div>
      ) : null}

      {step === 'days' ? (
        <div>
          <p className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-300">
            באילו ימים?
          </p>
          <div className="flex flex-wrap gap-2">
            {HEBREW_DAYS_SHORT.map((label, index) => (
              <Chip
                key={index}
                selected={draft.days.includes(index)}
                label={`יום ${label}`}
                onClick={() =>
                  update({
                    days: draft.days.includes(index)
                      ? draft.days.filter((day) => day !== index)
                      : [...draft.days, index].sort((a, b) => a - b),
                  })
                }
              >
                {label}
              </Chip>
            ))}
          </div>
        </div>
      ) : null}

      {step === 'conditions' ? (
        <div className="space-y-2">
          <p className="text-sm text-slate-600 dark:text-slate-300">
            בובי יפעיל את האוטומציה רק אם התנאים מתקיימים.
          </p>
          {draft.conditions.length === 0 ? (
            <p className="rounded-xl bg-slate-50 p-3 text-sm text-slate-500 dark:bg-slate-900/40 dark:text-slate-400">
              אין תנאים. האוטומציה תרוץ תמיד.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {draft.conditions.map((condition, index) => (
                <li
                  key={index}
                  className="flex items-center justify-between rounded-xl border border-slate-200 p-2.5 text-sm dark:border-slate-700"
                >
                  <span className="text-slate-800 dark:text-slate-200">
                    {condition.label} {condition.operator ?? ''} {String(condition.value ?? '')}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      update({ conditions: draft.conditions.filter((_, i) => i !== index) })
                    }
                  >
                    הסרה
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <Button
            variant="secondary"
            size="sm"
            onClick={() =>
              update({
                conditions: [
                  ...draft.conditions,
                  { type: 'presence', label: 'יש מישהו בבית', operator: null, value: true },
                ],
              })
            }
          >
            הוספת תנאי
          </Button>
        </div>
      ) : null}

      {step === 'summary' ? (
        <div className="space-y-3">
          {previewMutation.isError ? (
            <ErrorState
              error={previewMutation.error}
              fallbackMessage="לא הצלחתי להכין תצוגה מקדימה"
            />
          ) : null}

          {preview ? (
            <>
              <div className="rounded-2xl bg-bobi-50 p-4 dark:bg-bobi-500/10">
                <p className="text-xs font-medium text-bobi-700 dark:text-bobi-300">
                  זה מה שיקרה
                </p>
                <p className="mt-1 text-base font-semibold text-slate-900 dark:text-slate-100">
                  {preview.summary}
                </p>
              </div>

              {preview.lines.length > 0 ? (
                <ul className="space-y-1 rounded-xl bg-slate-50 p-3 dark:bg-slate-900/40">
                  {preview.lines.map((line, index) => (
                    <li
                      key={index}
                      className="text-sm text-slate-600 dark:text-slate-300"
                    >
                      {line.text}
                    </li>
                  ))}
                </ul>
              ) : null}

              {preview.warnings.length > 0 ? (
                <ul className="space-y-1 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
                  {preview.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : null}

          {confirmMutation.isError ? (
            <ErrorState
              error={confirmMutation.error}
              fallbackMessage="לא הצלחתי לשמור את האוטומציה"
            />
          ) : null}

          <p className="text-xs text-slate-500 dark:text-slate-400">
            בשלב זה השמירה נרשמת בממשק הניהול בלבד ואינה משנה את מערכת הבית.
          </p>
        </div>
      ) : null}
    </Modal>
  );
}
