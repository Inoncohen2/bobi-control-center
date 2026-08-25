import { Link } from 'react-router-dom';
import { History, Lock } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { QueryBoundary } from '@/components/state/QueryBoundary';
import { useSettings } from '@/hooks/queries';
import type { SettingField } from '@/types/api';
import { iconFor } from '@/utils/icons';

function renderValue(field: SettingField) {
  if (field.secret) {
    // The backend already replaced the value with a mask; it never ships the
    // real secret to the browser.
    return (
      <span className="inline-flex items-center gap-1.5 font-mono text-slate-500 dark:text-slate-400">
        <Lock aria-hidden="true" size={13} />
        {String(field.value)}
      </span>
    );
  }
  if (typeof field.value === 'boolean') return field.value ? 'מופעל' : 'כבוי';
  if (field.value === null || field.value === undefined) return '—';
  return String(field.value);
}

function FieldRow({ field }: { field: SettingField }) {
  return (
    <div className="border-b border-slate-100 py-3 last:border-0 dark:border-slate-700/60">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <dt className="text-sm text-slate-600 dark:text-slate-300">{field.label}</dt>
        <dd className="text-sm font-medium text-slate-900 dark:text-slate-100">
          {renderValue(field)}
        </dd>
      </div>
      {field.help ? (
        <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">{field.help}</p>
      ) : null}
    </div>
  );
}

export function SettingsPage() {
  const query = useSettings();

  return (
    <>
      <PageHeader
        title="הגדרות"
        description="איך בובי מוגדר. בשלב זה ההגדרות מוצגות לצפייה בלבד."
        action={
          <Link
            to="/audit"
            className="inline-flex h-10 items-center gap-2 rounded-xl bg-slate-100 px-4 text-sm font-medium text-slate-800 transition-colors hover:bg-slate-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-500 dark:bg-slate-700 dark:text-slate-100 dark:hover:bg-slate-600"
          >
            <History aria-hidden="true" size={16} />
            יומן פעולות
          </Link>
        }
      />

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחתי לטעון את ההגדרות"
        onRetry={() => void query.refetch()}
      >
        {(settings) => (
          <div className="space-y-4">
            {settings.read_only ? (
              <Card className="border-bobi-200 bg-bobi-50/60 dark:border-bobi-500/30 dark:bg-bobi-500/10">
                <p className="text-sm text-bobi-900 dark:text-bobi-200">{settings.note}</p>
              </Card>
            ) : null}

            {settings.sections.map((section) => {
              const Icon = iconFor(section.icon);
              return (
                <Card key={section.id} as="section">
                  <div className="mb-2 flex items-start gap-3">
                    <span
                      aria-hidden="true"
                      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-bobi-50 text-bobi-600 dark:bg-bobi-500/15 dark:text-bobi-300"
                    >
                      <Icon size={20} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <h2 className="font-semibold text-slate-900 dark:text-slate-100">
                        {section.title}
                      </h2>
                      {section.description ? (
                        <p className="text-sm text-slate-500 dark:text-slate-400">
                          {section.description}
                        </p>
                      ) : null}
                    </div>
                    {section.fields.some((field) => field.secret) ? (
                      <Badge tone="muted">
                        <Lock aria-hidden="true" size={11} />
                        מוסתר
                      </Badge>
                    ) : null}
                  </div>
                  <dl>
                    {section.fields.map((field) => (
                      <FieldRow key={field.key} field={field} />
                    ))}
                  </dl>
                </Card>
              );
            })}
          </div>
        )}
      </QueryBoundary>
    </>
  );
}
