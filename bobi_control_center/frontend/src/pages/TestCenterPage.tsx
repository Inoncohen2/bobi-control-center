import { useState } from 'react';
import { ChevronDown, ClipboardCopy, Play, ShieldCheck, TriangleAlert } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, SectionTitle } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { ErrorState } from '@/components/state/QueryBoundary';
import { useRunProbe } from '@/hooks/queries';
import {
  buildPipeline,
  stepStatusLabel,
  understandingRows,
  type PipelineStep,
} from '@/features/probe/pipeline';
import type { BridgeProbe } from '@/types/api';
import { probeStatusLabel } from '@/utils/format';
import { cn } from '@/utils/cn';

const EXAMPLES = [
  'כבה מזגן הורים ב-1:30 בלילה',
  'תדליק את אור המטבח',
  'מה הטמפרטורה בסלון',
  'תוסיף משימה לקנות חלב',
  'קשקוש שבובי לא יבין',
];

const STEP_TONES: Record<PipelineStep['status'], string> = {
  ok: 'border-emerald-200 bg-emerald-50/60 dark:border-emerald-500/30 dark:bg-emerald-500/10',
  warning: 'border-amber-200 bg-amber-50/60 dark:border-amber-500/30 dark:bg-amber-500/10',
  skipped: 'border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/60',
  failed: 'border-rose-200 bg-rose-50/60 dark:border-rose-500/30 dark:bg-rose-500/10',
};

function PipelineStepCard({
  step,
  index,
  total,
}: {
  step: PipelineStep;
  index: number;
  total: number;
}) {
  return (
    <li className="flex flex-col items-stretch">
      <div className={cn('rounded-2xl border p-3', STEP_TONES[step.status])}>
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{step.label}</p>
          {/* Status is spelled out, never conveyed by colour alone. */}
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {stepStatusLabel(step.status)}
          </span>
        </div>
        <p className="mt-1 break-words text-sm text-slate-700 dark:text-slate-200">{step.value}</p>
        {step.detail ? (
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{step.detail}</p>
        ) : null}
      </div>
      {index < total - 1 ? (
        <span aria-hidden="true" className="flex justify-center py-1 text-slate-300">
          <ChevronDown size={16} />
        </span>
      ) : null}
    </li>
  );
}

function ProbeReport({ result, text }: { result: BridgeProbe; text: string }) {
  const [copied, setCopied] = useState(false);
  const steps = buildPipeline(result, text);
  const rows = understandingRows(result);

  const copyJson = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(result, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be denied; the JSON stays visible below regardless.
    }
  };

  return (
    <div className="space-y-4">
      {/* The single most important message on this page. */}
      <div className="flex items-start gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-500/30 dark:bg-emerald-500/10">
        <ShieldCheck
          aria-hidden="true"
          size={20}
          className="mt-0.5 shrink-0 text-emerald-600 dark:text-emerald-400"
        />
        <div>
          <p className="font-semibold text-emerald-900 dark:text-emerald-200">
            בדיקה בלבד — לא בוצעה שום פעולה
          </p>
          <p className="text-sm text-emerald-800 dark:text-emerald-300/90">
            בובי ניתח את הטקסט במצב probe_only. אף מכשיר לא הופעל ואף תזמון לא נוצר.
          </p>
        </div>
      </div>

      <Card>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Badge tone={result.handled ? 'ok' : 'warning'} dot>
            {result.handled ? 'הובן' : 'לא הובן'}
          </Badge>
          {result.status ? <Badge tone="neutral">{probeStatusLabel(result.status)}</Badge> : null}
          {result.skill ? <Badge tone="info">{result.skill}</Badge> : null}
          {result.terminal === true ? <Badge tone="muted">סופי</Badge> : null}
        </div>

        <ol className="space-y-0">
          {steps.map((step, index) => (
            <PipelineStepCard
              key={step.id}
              step={step}
              index={index}
              total={steps.length}
            />
          ))}
        </ol>
      </Card>

      {rows.length > 0 ? (
        <Card>
          <h3 className="mb-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
            מה בובי הבין
          </h3>
          <dl className="divide-y divide-slate-100 dark:divide-slate-700/60">
            {rows.map(([label, value]) => (
              <div key={label} className="flex items-baseline justify-between gap-4 py-2">
                <dt className="text-sm text-slate-500 dark:text-slate-400">{label}</dt>
                <dd className="text-sm font-medium text-slate-900 dark:text-slate-100">{value}</dd>
              </div>
            ))}
          </dl>
        </Card>
      ) : null}

      {result.schedule_valid === false || result.error ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-500/30 dark:bg-amber-500/10">
          <p className="flex items-center gap-2 font-medium text-amber-900 dark:text-amber-200">
            <TriangleAlert aria-hidden="true" size={16} />
            הערות
          </p>
          <ul className="mt-1.5 list-inside list-disc space-y-1 text-sm text-amber-800 dark:text-amber-200/90">
            {result.schedule_reason ? <li>{result.schedule_reason}</li> : null}
            {result.error ? <li>{result.error}</li> : null}
          </ul>
        </div>
      ) : null}

      <details className="rounded-2xl border border-slate-200 dark:border-slate-700">
        <summary className="cursor-pointer px-4 py-3 text-sm text-slate-600 dark:text-slate-400">
          תוצאה מלאה (JSON)
        </summary>
        <div className="border-t border-slate-200 p-4 dark:border-slate-700">
          <Button
            variant="secondary"
            size="sm"
            icon={<ClipboardCopy size={14} />}
            onClick={() => void copyJson()}
          >
            {copied ? 'הועתק' : 'העתקה'}
          </Button>
          <pre
            dir="ltr"
            className="mt-3 max-h-80 overflow-auto rounded-xl bg-slate-50 p-3 text-left text-xs text-slate-700 dark:bg-slate-900/50 dark:text-slate-300"
          >
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      </details>
    </div>
  );
}

export function TestCenterPage() {
  const [text, setText] = useState('');
  const [submitted, setSubmitted] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const probe = useRunProbe();

  const submit = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return;
    setSubmitted(trimmed);
    setHistory((current) => [trimmed, ...current.filter((item) => item !== trimmed)].slice(0, 10));
    probe.mutate(trimmed);
  };

  return (
    <>
      <PageHeader
        title="בדיקות"
        description="כתבו לבובי כל דבר וראו בדיוק איך הוא מבין אותו — בלי שיבצע שום פעולה."
      />

      <Card className="mb-5">
        <label
          htmlFor="probe-input"
          className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-300"
        >
          כתוב משהו שהיית שולח לבובי
        </label>
        <textarea
          id="probe-input"
          rows={3}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) submit(text);
          }}
          placeholder="לדוגמה: כבה מזגן הורים ב-1:30 בלילה"
          className="w-full resize-y rounded-xl border border-slate-300 bg-white p-3 text-base text-slate-900 placeholder:text-slate-400 focus:border-bobi-500 focus:outline-none focus:ring-2 focus:ring-bobi-500/30 dark:border-slate-600 dark:bg-slate-900/40 dark:text-slate-100"
        />

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {/* The only submit control on this page. There is deliberately no
              "execute" button anywhere in the Test Center. */}
          <Button
            icon={<Play size={16} />}
            loading={probe.isPending}
            disabled={text.trim().length === 0}
            onClick={() => submit(text)}
          >
            בדוק בלי לבצע
          </Button>
          <span className="text-xs text-slate-400 dark:text-slate-500">
            שום פעולה לא תתבצע בפועל
          </span>
        </div>

        <div className="mt-4">
          <p className="mb-2 text-xs font-medium text-slate-500 dark:text-slate-400">דוגמאות</p>
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => {
                  setText(example);
                  submit(example);
                }}
                className="rounded-full bg-slate-100 px-3 py-1.5 text-xs text-slate-600 transition-colors hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-300 dark:hover:bg-slate-600"
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      </Card>

      {probe.isError ? (
        <div className="mb-5">
          <ErrorState
            error={probe.error}
            fallbackMessage="לא הצלחתי לשלוח את הטקסט לבדיקה"
            onRetry={() => submit(submitted)}
          />
        </div>
      ) : null}

      {probe.data ? <ProbeReport result={probe.data} text={submitted} /> : null}

      {history.length > 0 ? (
        <section className="mt-8" aria-labelledby="history-heading">
          <SectionTitle>
            <span id="history-heading">בדיקות אחרונות</span>
          </SectionTitle>
          <Card className="p-0">
            <ul className="divide-y divide-slate-100 dark:divide-slate-700/60">
              {history.map((entry) => (
                <li key={entry}>
                  <button
                    type="button"
                    onClick={() => {
                      setText(entry);
                      submit(entry);
                    }}
                    className="w-full px-4 py-3 text-right text-sm text-slate-700 transition-colors hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-700/40"
                  >
                    {entry}
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        </section>
      ) : null}
    </>
  );
}
