import { Lock, PlugZap } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { ReadOnlyNotice } from '@/components/ui/ReadOnly';
import { QueryBoundary } from '@/components/state/QueryBoundary';
import { useTheme, type ThemeChoice } from '@/hooks/useTheme';
import { useConnection, useStatus } from '@/hooks/queries';

const THEME_LABELS: Record<ThemeChoice, string> = {
  system: 'לפי המערכת',
  light: 'בהיר',
  dark: 'כהה',
};

const ADAPTER_LABELS: Record<string, string> = {
  home_assistant: 'Home Assistant (גשר בובי)',
  mock: 'מצב הדגמה — נתונים מדומים',
};

function Row({ label, value, help }: { label: string; value: React.ReactNode; help?: string }) {
  return (
    <div className="border-b border-slate-100 py-3 last:border-0 dark:border-slate-700/60">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <dt className="text-sm text-slate-600 dark:text-slate-300">{label}</dt>
        <dd className="text-sm font-medium text-slate-900 dark:text-slate-100">{value}</dd>
      </div>
      {help ? <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">{help}</p> : null}
    </div>
  );
}

export function SettingsPage() {
  const connection = useConnection();
  const status = useStatus();
  const { theme, setTheme } = useTheme();

  return (
    <>
      <PageHeader title="הגדרות" description="איך היישום מחובר ומה מצבו." />

      <ReadOnlyNotice className="mb-4">
        שלב 2 הוא קריאה בלבד. שינוי הגדרות של בובי יהיה זמין בשלב הבא.
      </ReadOnlyNotice>

      <div className="space-y-4">
        <QueryBoundary
          isLoading={connection.isLoading}
          error={connection.error}
          data={connection.data}
          errorMessage="לא הצלחתי לבדוק את מצב החיבור"
          loadingLabel="בודק חיבור…"
          onRetry={() => void connection.refetch()}
        >
          {(info) => (
            <Card as="section">
              <div className="mb-2 flex items-start gap-3">
                <span
                  aria-hidden="true"
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-bobi-50 text-bobi-600 dark:bg-bobi-500/15 dark:text-bobi-300"
                >
                  <PlugZap size={20} />
                </span>
                <div className="min-w-0 flex-1">
                  <h2 className="font-semibold text-slate-900 dark:text-slate-100">
                    חיבור ל-Home Assistant
                  </h2>
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    מאיפה מגיעים הנתונים שמוצגים ביישום.
                  </p>
                </div>
                <Badge tone={info.connected ? 'ok' : 'warning'} dot>
                  {info.connected ? 'מחובר' : 'לא מחובר'}
                </Badge>
              </div>
              <dl>
                <Row
                  label="מקור נתונים"
                  value={ADAPTER_LABELS[info.adapter] ?? info.adapter}
                  help={info.detail ?? undefined}
                />
                <Row
                  label="אימות"
                  value={
                    <span className="inline-flex items-center gap-1.5">
                      <Lock aria-hidden="true" size={13} />
                      טוקן שרת בלבד
                    </span>
                  }
                  help="הטוקן נשמר בשרת של היישום ואינו נחשף לדפדפן."
                />
                <Row label="שלב" value={`שלב ${info.phase}`} />
                <Row
                  label="מצב כתיבה"
                  value={info.writes_enabled ? 'מאופשר' : 'חסום'}
                  help="בשלב זה היישום קורא נתונים בלבד ואינו משנה דבר."
                />
              </dl>
            </Card>
          )}
        </QueryBoundary>

        {status.data ? (
          <Card as="section">
            <h2 className="mb-2 font-semibold text-slate-900 dark:text-slate-100">בובי</h2>
            <dl>
              {status.data.version ? (
                <Row label="גרסת בובי" value={status.data.version} />
              ) : null}
              {status.data.uptime ? <Row label="פעיל" value={status.data.uptime} /> : null}
              {/* Reported by the backend, so it can never drift from what is running. */}
              {connection.data?.app_version ? (
                <Row label="גרסת ממשק" value={connection.data.app_version} />
              ) : null}
            </dl>
          </Card>
        ) : null}

        <Card as="section">
          <h2 className="mb-2 font-semibold text-slate-900 dark:text-slate-100">תצוגה</h2>
          <p className="mb-3 text-sm text-slate-500 dark:text-slate-400">
            העדפה מקומית לדפדפן הזה בלבד.
          </p>
          <div className="flex flex-wrap gap-2">
            {(['system', 'light', 'dark'] as ThemeChoice[]).map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={theme === option}
                onClick={() => setTheme(option)}
                className={
                  theme === option
                    ? 'rounded-full bg-bobi-600 px-3.5 py-1.5 text-sm font-medium text-white'
                    : 'rounded-full bg-slate-100 px-3.5 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-300'
                }
              >
                {THEME_LABELS[option]}
              </button>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}
