import { CheckCircle2, Home, MessageCircle, ShieldCheck, UserRound } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';

import { setupApi, type SetupRole, type SetupSnapshot } from '@/api/setup';
import { toDisplayError } from '@/api/client';
import { Badge } from '@/components/ui/Badge';
import { Card, CardHeader } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';

const inputClass =
  'mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-bobi-400 focus:ring-2 focus:ring-bobi-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-bobi-500/20';
const primaryButton =
  'rounded-xl bg-bobi-600 px-4 py-2 text-sm font-semibold text-white hover:bg-bobi-700 disabled:cursor-not-allowed disabled:opacity-50';
const secondaryButton =
  'rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200';

const MISSING_LABELS: Record<string, string> = {
  messaging_provider: 'חיבור WhatsApp',
  user: 'משתמש',
  user_identity: 'מספר WhatsApp מקושר',
};

function StepBadge({ done, children }: { done: boolean; children: string }) {
  return (
    <span
      className={
        done
          ? 'inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300'
          : 'inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-500 dark:bg-slate-700 dark:text-slate-300'
      }
    >
      {done ? <CheckCircle2 size={13} /> : null}
      {children}
    </span>
  );
}

export function NextSetupPage() {
  const [snapshot, setSnapshot] = useState<SetupSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const [endpoint, setEndpoint] = useState('');
  const [session, setSession] = useState('default');
  const [engine, setEngine] = useState('GOWS');
  const [displayName, setDisplayName] = useState('');
  const [role, setRole] = useState<SetupRole>('owner');
  const [identityUserKey, setIdentityUserKey] = useState('');
  const [externalId, setExternalId] = useState('');

  const refresh = useCallback(async () => {
    try {
      const next = await setupApi.status();
      setSnapshot(next);
      setIdentityUserKey((current) => current || next.users[0]?.user_key || '');
      setError('');
    } catch (cause) {
      const apiError = toDisplayError(cause, 'לא הצלחתי לטעון את אשף ההגדרה');
      setError(
        apiError.status === 404
          ? 'Bobi Next Setup כבוי כרגע. זה צפוי כל עוד סביבת הפיתוח לא הופעלה.'
          : apiError.message,
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const provider = snapshot?.providers.find((item) => item.provider_key === 'whatsapp') ?? null;
  const providerDone = Boolean(provider?.enabled);
  const usersDone = Boolean(snapshot?.users.some((user) => user.enabled));
  const identityDone = Boolean(snapshot && snapshot.linked_identities > 0);
  const ready = Boolean(snapshot?.setup.ready);
  const completed = Boolean(snapshot?.setup.completed);

  const selectedUser = useMemo(
    () => snapshot?.users.find((user) => user.user_key === identityUserKey) ?? null,
    [identityUserKey, snapshot],
  );

  async function run(label: string, action: () => Promise<void>) {
    setBusy(label);
    setError('');
    try {
      await action();
      await refresh();
    } catch (cause) {
      setError(toDisplayError(cause, 'הפעולה נכשלה').message);
    } finally {
      setBusy('');
    }
  }

  async function saveWhatsApp(event: FormEvent) {
    event.preventDefault();
    await run('provider', async () => {
      await setupApi.saveProvider({
        provider_key: 'whatsapp',
        provider_type: 'waha',
        display_name: 'WhatsApp',
        enabled: true,
        endpoint: endpoint.trim(),
        session: session.trim() || 'default',
        engine,
        config: {},
      });
    });
  }

  async function addUser(event: FormEvent) {
    event.preventDefault();
    if (!displayName.trim()) return;
    await run('user', async () => {
      const user = await setupApi.createUser({ display_name: displayName.trim(), role });
      setIdentityUserKey(user.user_key);
      setDisplayName('');
    });
  }

  async function linkIdentity(event: FormEvent) {
    event.preventDefault();
    if (!identityUserKey || !externalId.trim()) return;
    await run('identity', async () => {
      await setupApi.linkIdentity({
        provider_key: 'whatsapp',
        external_id: externalId.trim(),
        user_key: identityUserKey,
        identity_label: selectedUser?.display_name ?? '',
      });
      setExternalId('');
    });
  }

  async function completeSetup() {
    await run('complete', async () => {
      const next = await setupApi.complete();
      setSnapshot(next);
    });
  }

  return (
    <>
      <PageHeader
        title="הגדרת Bobi Next"
        description="אשף התקנה מקומי: Home Assistant מזוהה אוטומטית, ואת מגדירה רק WhatsApp, משתמשים והרשאות."
        action={
          <Badge tone={completed ? 'ok' : ready ? 'warning' : 'muted'} dot>
            {completed ? 'הוגדר' : ready ? 'מוכן לסיום' : 'בתהליך'}
          </Badge>
        }
      />

      <div className="mb-4 flex flex-wrap gap-2">
        <StepBadge done>Home Assistant</StepBadge>
        <StepBadge done={providerDone}>WhatsApp</StepBadge>
        <StepBadge done={usersDone}>משתמשים</StepBadge>
        <StepBadge done={identityDone}>קישור זהות</StepBadge>
      </div>

      {error ? (
        <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/30 dark:text-rose-300">
          {error}
        </div>
      ) : null}

      {loading ? (
        <Card>טוען את מצב ההגדרה…</Card>
      ) : (
        <div className="space-y-4">
          <Card as="section">
            <CardHeader
              icon={<Home size={20} />}
              title="1. Home Assistant"
              description="Bobi Next יקרא את ה-Device/Entity Registry והיכולות החיות בלי Scripts או Helpers של Bobi."
              action={<Badge tone="ok">אוטומטי</Badge>}
            />
          </Card>

          <Card as="section">
            <CardHeader
              icon={<MessageCircle size={20} />}
              title="2. WhatsApp"
              description="כרגע מחברים את WAHA הקיים. QR pairing מובנה יתווסף בשלב הבא ולא יוצג כפעיל לפני שיש API אמיתי."
              action={providerDone ? <Badge tone="ok">נשמר</Badge> : undefined}
            />
            <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={(event) => void saveWhatsApp(event)}>
              <label className="text-sm text-slate-600 dark:text-slate-300 sm:col-span-2">
                כתובת WAHA
                <input
                  className={inputClass}
                  value={endpoint}
                  onChange={(event) => setEndpoint(event.target.value)}
                  placeholder="http://waha:3000"
                  required
                />
              </label>
              <label className="text-sm text-slate-600 dark:text-slate-300">
                Session
                <input
                  className={inputClass}
                  value={session}
                  onChange={(event) => setSession(event.target.value)}
                  required
                />
              </label>
              <label className="text-sm text-slate-600 dark:text-slate-300">
                Engine
                <select className={inputClass} value={engine} onChange={(event) => setEngine(event.target.value)}>
                  <option value="GOWS">GOWS</option>
                  <option value="NOWEB">NOWEB</option>
                  <option value="WEBJS">WEBJS</option>
                </select>
              </label>
              <div className="sm:col-span-2">
                <button className={primaryButton} disabled={busy !== ''} type="submit">
                  {busy === 'provider' ? 'שומר…' : providerDone ? 'עדכן חיבור' : 'שמור חיבור'}
                </button>
              </div>
            </form>
          </Card>

          <Card as="section">
            <CardHeader
              icon={<UserRound size={20} />}
              title="3. משתמשים"
              description="כל מספר WhatsApp מקושר למשתמש Bobi יציב עם זיכרון והרשאות משלו."
              action={usersDone ? <Badge tone="ok">{snapshot?.users.length ?? 0} משתמשים</Badge> : undefined}
            />
            <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={(event) => void addUser(event)}>
              <label className="text-sm text-slate-600 dark:text-slate-300">
                שם
                <input
                  className={inputClass}
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  placeholder="לדוגמה: הודיה"
                  required
                />
              </label>
              <label className="text-sm text-slate-600 dark:text-slate-300">
                תפקיד
                <select className={inputClass} value={role} onChange={(event) => setRole(event.target.value as SetupRole)}>
                  <option value="owner">בעלים</option>
                  <option value="admin">מנהל</option>
                  <option value="member">בן משפחה</option>
                  <option value="guest">אורח</option>
                </select>
              </label>
              <div className="sm:col-span-2">
                <button className={primaryButton} disabled={busy !== ''} type="submit">
                  {busy === 'user' ? 'מוסיף…' : 'הוסף משתמש'}
                </button>
              </div>
            </form>

            {snapshot && snapshot.users.length > 0 ? (
              <div className="mt-4 divide-y divide-slate-100 rounded-xl border border-slate-100 px-3 dark:divide-slate-700 dark:border-slate-700">
                {snapshot.users.map((user) => (
                  <div key={user.user_key} className="flex items-center justify-between gap-3 py-3 text-sm">
                    <span className="font-medium text-slate-900 dark:text-slate-100">{user.display_name}</span>
                    <span className="text-slate-500 dark:text-slate-400">
                      {user.role} · {user.policy.can_approve ? 'יכול לאשר פעולות רגישות' : 'ללא אישורים רגישים'}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
          </Card>

          <Card as="section">
            <CardHeader
              icon={<ShieldCheck size={20} />}
              title="4. קישור מספר WhatsApp והרשאה"
              description="המספר עצמו לא נשמר בטקסט גלוי במסד הנתונים; Bobi שומר fingerprint מקומי ומקשר אותו למשתמש."
              action={identityDone ? <Badge tone="ok">מקושר</Badge> : undefined}
            />
            <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={(event) => void linkIdentity(event)}>
              <label className="text-sm text-slate-600 dark:text-slate-300">
                משתמש
                <select
                  className={inputClass}
                  value={identityUserKey}
                  onChange={(event) => setIdentityUserKey(event.target.value)}
                  required
                >
                  <option value="">בחרי משתמש</option>
                  {snapshot?.users.map((user) => (
                    <option key={user.user_key} value={user.user_key}>{user.display_name}</option>
                  ))}
                </select>
              </label>
              <label className="text-sm text-slate-600 dark:text-slate-300">
                מספר / WhatsApp ID
                <input
                  className={inputClass}
                  value={externalId}
                  onChange={(event) => setExternalId(event.target.value)}
                  placeholder="מספר בינלאומי או מזהה WhatsApp"
                  required
                />
              </label>
              <div className="sm:col-span-2">
                <button className={primaryButton} disabled={busy !== '' || !providerDone || !usersDone} type="submit">
                  {busy === 'identity' ? 'מקשר…' : 'קשר למשתמש'}
                </button>
              </div>
            </form>
          </Card>

          <Card as="section" className={ready ? 'border-emerald-200 dark:border-emerald-900/50' : undefined}>
            <CardHeader
              icon={<CheckCircle2 size={20} />}
              title="סיום"
              description={
                ready
                  ? 'כל דרישות הסטאפ הבסיסיות הושלמו. אפשר לסמן את ההתקנה כמוכנה.'
                  : `עדיין חסר: ${(snapshot?.setup.missing_steps ?? []).map((item) => MISSING_LABELS[item] ?? item).join(', ') || 'טעינת נתונים'}`
              }
              action={completed ? <Badge tone="ok">מוכן</Badge> : undefined}
            />
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                className={primaryButton}
                disabled={!ready || busy !== '' || completed}
                onClick={() => void completeSetup()}
                type="button"
              >
                {busy === 'complete' ? 'מסיים…' : completed ? 'ההגדרה הושלמה' : 'סיים הגדרה'}
              </button>
              <button className={secondaryButton} disabled={busy !== ''} onClick={() => void refresh()} type="button">
                רענן מצב
              </button>
            </div>
          </Card>
        </div>
      )}
    </>
  );
}
