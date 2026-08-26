/**
 * The dashboard's answer to "can I change anything from here, and what changed?"
 *
 * Two facts a household cannot get anywhere else on the front page: whether the
 * control centre is able to write at all, and what it did recently. Both are
 * read-only, and the card never appears as a fault — management being off is
 * the normal, expected state and is drawn as a switch rather than as an error.
 */

import { Link } from 'react-router-dom';
import { ChevronLeft, ShieldCheck, ShieldOff } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card, SectionTitle } from '@/components/ui/Card';
import { useAudit, useManagementContract } from '@/hooks/queries';

const RESOURCE_LABELS: Record<string, string> = {
  tasks: 'משימות',
  features: 'תכונות',
  settings: 'הגדרות',
  users: 'משתמשים',
  shabbat: 'שעון שבת',
  rules: 'אוטומציות',
  calendar: 'יומן',
  devices: 'מכשירים',
  system: 'מערכת',
};

const RESULT_TONES: Record<string, 'ok' | 'warning' | 'error' | 'neutral'> = {
  committed: 'ok',
  committed_unverified: 'warning',
  failed: 'error',
  refused: 'error',
};

const RESULT_LABELS: Record<string, string> = {
  committed: 'בוצע ואומת',
  committed_unverified: 'בוצע, לא אומת',
  failed: 'לא בוצע',
  refused: 'נדחה',
};

export function ManagementSummary() {
  const contract = useManagementContract();
  const audit = useAudit();

  const available = contract.data?.available ?? false;
  const writesEnabled = contract.data?.writes_enabled ?? false;
  const managed = (contract.data?.resources ?? []).filter((entry) => entry.available);
  // Previews are most of the trail and none of the news.
  const recent = (audit.data?.records ?? []).filter((entry) => entry.stage === 'commit').slice(0, 3);

  return (
    <section aria-labelledby="management-heading">
      <SectionTitle>
        <span id="management-heading">מרכז הניהול</span>
      </SectionTitle>
      <Card>
        <div className="flex flex-wrap items-center gap-2">
          {available ? (
            <Badge tone={writesEnabled ? 'ok' : 'muted'} dot>
              {writesEnabled ? 'שינויים מהאתר פעילים' : 'שינויים מהאתר כבויים'}
            </Badge>
          ) : (
            <Badge tone="muted" dot>
              ניהול עדיין לא הופעל ב-Home Assistant
            </Badge>
          )}
          {available ? (
            <span
              aria-hidden
              className="text-slate-400"
            >
              {writesEnabled ? <ShieldCheck size={16} /> : <ShieldOff size={16} />}
            </span>
          ) : null}
        </div>

        {managed.length > 0 ? (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {managed.map((entry) => (
              <Badge key={entry.id} tone="neutral">
                {RESOURCE_LABELS[entry.id] ?? entry.label}
              </Badge>
            ))}
          </div>
        ) : null}

        {recent.length > 0 ? (
          <ul className="mt-4 space-y-2">
            {recent.map((entry) => (
              <li key={entry.id} className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm text-slate-700 dark:text-slate-200">
                  {RESOURCE_LABELS[entry.resource_type] ?? entry.resource_type} · {entry.operation}
                </span>
                <Badge tone={RESULT_TONES[entry.result] ?? 'neutral'}>
                  {RESULT_LABELS[entry.result] ?? entry.result}
                </Badge>
              </li>
            ))}
          </ul>
        ) : null}

        <Link
          to="/activity"
          className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-bobi-700 hover:underline dark:text-bobi-300"
        >
          יומן הפעילות
          <ChevronLeft aria-hidden size={16} />
        </Link>
      </Card>
    </section>
  );
}
