import { FolderArchive } from 'lucide-react';
import { useState, type FormEvent } from 'react';

import { toDisplayError } from '@/api/client';
import { setupApi, type ArchiveSetupSnapshot, type ArchiveStorageMode } from '@/api/setup';
import { Badge } from '@/components/ui/Badge';
import { Card, CardHeader } from '@/components/ui/Card';

const inputClass =
  'mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-bobi-400 focus:ring-2 focus:ring-bobi-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100';
const buttonClass =
  'rounded-xl bg-bobi-600 px-4 py-2 text-sm font-semibold text-white hover:bg-bobi-700 disabled:cursor-not-allowed disabled:opacity-50';

const REASONS: Record<string, string> = {
  archive_generic_protocol_required: 'החיבור הזה אינו תומך בארכיון מסמכים כללי. יש להשתמש בחיבור ארכיון מתאים.',
  archive_installation_mismatch: 'מפתח הגישה שייך להתקנה אחרת. הזיני מפתח עבור ההתקנה הזו.',
  archive_provider_not_configured: 'יש להגדיר חיבור ענן ולבדוק אותו לפני הבחירה.',
  archive_provider_ambiguous: 'קיים יותר מחיבור ארכיון פעיל. יש להשאיר חיבור אחד פעיל.',
  archive_secret_missing: 'חסר מפתח גישה לארכיון.',
  archive_secret_unavailable: 'לא ניתן לקרוא את מפתח הגישה השמור. הזיני אותו מחדש.',
  storage_unauthorized: 'מפתח הגישה לא התקבל. בדקי את המפתח וההרשאה.',
  storage_timeout: 'בדיקת החיבור התעכבה. אפשר לנסות שוב.',
  storage_unavailable: 'אחסון הענן אינו זמין כרגע. אפשר לנסות שוב.',
};

interface Props {
  initial: ArchiveSetupSnapshot;
  disabled: boolean;
  onSaved: () => Promise<void>;
  onBusyChange: (busy: boolean) => void;
}

export function ArchiveSetupCard({ initial, disabled, onSaved, onBusyChange }: Props) {
  const [mode, setMode] = useState<ArchiveStorageMode>(initial.mode);
  const [endpoint, setEndpoint] = useState(initial.cloud.endpoint);
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const blocked = disabled || busy;
  const tokenRequired = !initial.cloud.has_secret || endpoint.trim().replace(/\/+$/, '') !== initial.cloud.endpoint;

  async function save(event: FormEvent) {
    event.preventDefault();
    if (blocked) return;
    setBusy(true);
    onBusyChange(true);
    setError('');
    setMessage('');
    try {
      if (mode === 'cloud') {
        const saved = await setupApi.saveArchiveIntegration({
          integration_key: initial.cloud.integration_key || 'archive:primary',
          integration_type: 'bobi_archive',
          display_name: 'Document archive',
          endpoint: endpoint.trim(),
          enabled: true,
          secret_value: token.trim() || undefined,
          config: { archive_enabled: true },
        });
        setEndpoint(saved.endpoint);
        setToken('');
        const checked = await setupApi.checkArchive();
        if (!checked.cloud.ready || !checked.cloud.check_fresh) {
          setError(REASONS[checked.cloud.reason] || 'בדיקת החיבור לא הצליחה. אחסון הענן לא נבחר.');
          await onSaved();
          return;
        }
      }
      await setupApi.selectArchiveMode(mode);
      await onSaved();
      setMessage(mode === 'local' ? 'קבצים חדשים יישמרו באחסון המקומי.' : 'חיבור הענן נבדק ונבחר לשמירת קבצים חדשים.');
    } catch (cause) {
      setError(toDisplayError(cause, 'לא הצלחתי לשמור את הגדרת האחסון. אפשר לנסות שוב.').message);
      await onSaved();
    } finally {
      setToken('');
      setBusy(false);
      onBusyChange(false);
    }
  }

  return (
    <Card as="section">
      <CardHeader
        icon={<FolderArchive size={20} />}
        title="6. ארכיון מסמכים"
        description="בחרי היכן לשמור מסמכים שתבקשי מבובי לשמור. קבצים קיימים נשארים במיקום שבו נשמרו."
        action={<Badge tone={initial.ready ? 'ok' : 'warning'}>{initial.mode === 'local' ? 'מקומי' : initial.ready ? 'ענן נבדק' : 'נדרשת בדיקה'}</Badge>}
      />
      <form className="mt-4 space-y-3" onSubmit={(event) => void save(event)}>
        <fieldset disabled={blocked} className="space-y-3">
          <legend className="text-sm font-medium text-slate-700 dark:text-slate-200">אחסון לקבצים חדשים</legend>
          <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <input type="radio" name="archive-mode" value="local" checked={mode === 'local'} onChange={() => setMode('local')} />
            מקומי — בתוך התקנת Bobi
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <input type="radio" name="archive-mode" value="cloud" checked={mode === 'cloud'} onChange={() => setMode('cloud')} />
            ענן — חיבור ארכיון פרטי
          </label>
          {mode === 'cloud' ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-sm text-slate-600 dark:text-slate-300 sm:col-span-2">
                כתובת חיבור הארכיון
                <input className={inputClass} type="url" dir="ltr" value={endpoint} onChange={(event) => setEndpoint(event.target.value)} required />
              </label>
              <label className="text-sm text-slate-600 dark:text-slate-300 sm:col-span-2">
                מפתח גישה לארכיון
                <input className={inputClass} type="password" autoComplete="new-password" dir="ltr" value={token} onChange={(event) => setToken(event.target.value)} required={tokenRequired} minLength={32} maxLength={512} />
              </label>
              <p className="text-xs text-slate-500 dark:text-slate-400 sm:col-span-2">
                {initial.cloud.has_secret ? 'המפתח השמור נשאר ללא שינוי אם השדה ריק. שינוי כתובת דורש מפתח חדש.' : 'הזיני מפתח שהונפק עבור התקנת Bobi הזו. הוא יישמר מוצפן.'}
                {' '}הבדיקה אינה מעלה קובץ.
              </p>
            </div>
          ) : (
            <p className="text-sm text-slate-500 dark:text-slate-400">מוכן לשימוש ללא חיבור נוסף. הקבצים נשמרים עם נתוני Bobi.</p>
          )}
          <button className={buttonClass} disabled={blocked} type="submit">
            {busy ? 'שומר ובודק…' : mode === 'cloud' ? 'שמור, בדוק ובחר ענן' : 'בחר אחסון מקומי'}
          </button>
        </fieldset>
        {error ? <p role="alert" className="text-sm text-rose-700 dark:text-rose-300">{error}</p> : null}
        {message ? <p role="status" className="text-sm text-emerald-700 dark:text-emerald-300">{message}</p> : null}
      </form>
    </Card>
  );
}
