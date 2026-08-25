import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ChevronDown,
  ClipboardCopy,
  FlaskConical,
  Play,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, SectionTitle } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { ErrorState } from '@/components/state/QueryBoundary';
import { useProbeHistory, useRunProbe } from '@/hooks/queries';
import type { ProbeResult, ProbeStep } from '@/types/api';
import { PROBE_FAMILY_LABELS, timeAgo } from '@/utils/format';
import { cn } from '@/utils/cn';

const EXAMPLES = [
  'כבה מזגן הורים ב-1:30 בלילה',
  'תדליק את אור המטבח בשעה 19:00 בימי ראשון וחמישי',
  'מה הטמפרטורה בסלון',
  'תוסיף משימה לקנות חלב',
  'תדליק את הדוד',
];

const STEP_TONES: Record<ProbeStep['status'], string> = {
  ok: 'border-emerald-200 bg-emerald-50/60 dark:border-emerald-500/30 dark:bg-emerald-500/10',
  warning: 'border-amber-200 bg-amber-50/60 dark:border-amber-500/30 dark:bg-amber-500/10',
  skipped: 'border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/60',
  failed: 'border-rose-200 bg-rose-50/60 dark:border-rose-500/30 dark:bg-rose-500/10',
};

const STEP_STATUS_LABELS: Record<ProbeStep['status'], string> = {
  ok: 'תקין',
  warning: 'אזהרה',
  skipped: 'לא רלוונטי',
  failed: 'נכשל',
};

function PipelineStep({ step, index, total }: { step: ProbeStep; index: number; total: number }) {
  return (
    <li className="flex flex-col items-stretch">
      <div className={cn('rounded-2xl border p-3', STEP_TONES[step.status])}>
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{step.label}</p>
          {/* Status is spelled out, never conveyed by colour alone. */}
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {STEP_STATUS_LABELS[step.status]}
          </span>
        </div>
        {step.value ? (
          <p className="mt-1 break-words text-sm text-slate-700 dark:text-slate-200">
            {step.value}
          </p>
        ) : null}
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

function ProbeReport({ result }: { result: ProbeResult }) {
  const [copied, setCopied] = useState(false);

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
          <p className="font-semibold text-emerald-900 dark:text-emerald-200">✅ בדיקה בלבד</p>
          <p className="text-sm text-emerald-800 dark:text-emerald-300/90">
            לא בוצעה שום פעולה. אף מכשיר לא הופעל ואף תזמון לא נוצר.
          </p>
        </div>
      </div>

      <Card>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Badge tone="info">{PROBE_FAMILY_LABELS[result.family] ?? result.family}</Badge>
          {result.skill ? <Badge tone="neutral">{result.skill}</Badge> : null}
          <Badge tone={result.safe ? 'ok' : 'warning'} dot>
            {result.safe ? 'בטוח' : 'דורש אישור'}
          </Badge>
          <Badge tone="muted">ביטחון {Math.round(result.confidence * 100)}%</Badge>
          <Badge tone="muted">{result.duration_ms} ms</Badge>
        </div>

        <ol className="space-y-0">
          {result.steps.map((step, index) => (
            <PipelineStep
              key={step.id}
              step={step}
              index={index}
              total={result.steps.length}
            />
          ))}
        </ol>
      </Card>

      {result.warnings.length > 0 ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-500/30 dark:bg-amber-500/10">
          <p className="flex items-center gap-2 font-medium text-amber-900 dark:text-amber-200">
            <TriangleAlert aria-hidden="true" size={16} />
            הערות
          </p>
          <ul className="mt-1.5 list-inside list-disc space-y-1 text-sm text-amber-800 dark:text-amber-200/90">
            {result.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
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
  const probe = useRunProbe();
  const history = useProbeHistory();

  const submit = (value: string) => {
    const trimmed = value.trim();
    if (trimmed) probe.mutate(trimmed);
  };

  return (
    <>
      <PageHeader
        title="בדיקות"
        description="אפשר לכתוב לבובי כל דבר ולראות בדיוק איך הוא מבין אותו — בלי שיבצע שום פעולה."
        action={
          <Link
            to="/tests"
            className="inline-flex h-10 items-center gap-2 rounded-xl bg-slate-100 px-4 text-sm font-medium text-slate-800 transition-colors hover:bg-slate-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-500 dark:bg-slate-700 dark:text-slate-100 dark:hover:bg-slate-600"
          >
            <FlaskConical aria-hidden="true" size={16} />
            בדיקות אוטומטיות
          </Link>
        }
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
          <ErrorState error={probe.error} fallbackMessage="לא הצלחתי לבדוק את הטקסט" />
        </div>
      ) : null}

      {probe.data ? <ProbeReport result={probe.data} /> : null}

      {(history.data?.entries.length ?? 0) > 0 ? (
        <section className="mt-8" aria-labelledby="history-heading">
          <SectionTitle>
            <span id="history-heading">בדיקות אחרונות</span>
          </SectionTitle>
          <Card className="p-0">
            <ul className="divide-y divide-slate-100 dark:divide-slate-700/60">
              {(history.data?.entries ?? []).map((entry) => (
                <li key={entry.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setText(entry.text);
                      submit(entry.text);
                    }}
                    className="w-full px-4 py-3 text-right transition-colors hover:bg-slate-50 dark:hover:bg-slate-700/40"
                  >
                    <div className="flex items-baseline justify-between gap-3">
                      <p className="min-w-0 truncate text-sm font-medium text-slate-800 dark:text-slate-200">
                        {entry.text}
                      </p>
                      <span className="shrink-0 text-xs text-slate-400">
                        {timeAgo(entry.timestamp)}
                      </span>
                    </div>
                    <p className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">
                      {entry.summary}
                    </p>
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
