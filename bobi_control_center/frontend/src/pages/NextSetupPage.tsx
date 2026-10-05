import {
  CheckCircle2,
  Cpu,
  Home,
  MessageCircle,
  Search,
  ShieldCheck,
  UserRound,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';

import {
  setupApi,
  type HomeScanSummary,
  type SetupRole,
  type SetupSnapshot,
} from '@/api/setup';
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
  messaging_provider_config: 'כתובת WAHA תקינה',
  ai_provider: 'ספק AI פעיל',
  ai_provider_config: 'Endpoint ומודל AI',
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

function ScanMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-3 dark:bg-slate-800/70">
      <div className="text-lg font-semibold text-slate-900 dark:text-slate-100">{value}</div>
      <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
    </div>
  );
}

export function NextSetupPage() {
  const [snapshot, setSnapshot] = useState<SetupSnapshot | null>(null);
  const [homeScan, setHomeScan] = useState<HomeScanSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const [endpoint, setEndpoint] = useState('');
  const [wahaApiKey, setWahaApiKey] = useState('');
  const [session, setSession] = useState('default');
  const [engine, setEngine] = useState('GOWS');

  const [aiDisplayName, setAiDisplayName] = useState('Primary AI');
  const [aiEndpoint, setAiEndpoint] = useState('');
  const [aiModel, setAiModel] = useState('');
  const [aiApiKey, setAiApiKey] = useState('');

  const [displayName, setDisplayName] = useState('');
  const [role, setRole] = useState<SetupRole>('owner');
  const [identityUserKey, setIdentityUserKey] = useState('');
  const [externalId, setExternalId] = useState('');

  const refresh = useCallback(async () => {
    try {
      const next = await setupApi.status();
      setSnapshot(next);
      setIdentityUserKey((current) => current || next.users[0]?.user_key || '');

      const savedProvider = next.providers.find((item) => item.provider_key === 'whatsapp');
      if (savedProvider) {
        setSession(savedProvider.session || 'default');
        setEngine(savedProvider.engine || 'GOWS');
      }

      const activeAI = next.ai.providers.find(
        (item) => item.provider_key === next.ai.active_provider,
      );
      if (activeAI) {
        setAiDisplayName(activeAI.display_name || 'Primary AI');
        setAiModel(activeAI.model || '');
      }
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
  const providerDone = Boolean(snapshot?.messaging_configured);
  const aiDone = Boolean(snapshot?.ai.configured);
  const usersDone = Boolean(snapshot?.users.some((user) => user.enabled));
  const identityDone = Boolean(snapshot && snapshot.linked_identities > 0);
  const homeDone = Boolean(homeScan?.ok);
  const ready = Boolean(snapshot?.setup.ready);
  const completed = Boolean(snapshot?.setup.completed);

  const activeAI = useMemo(
    () =>
      snapshot?.ai.providers.find((item) => item.provider_key === snapshot.ai.active_provider) ??
      null,
    [snapshot],
  );

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

  async function scanHome() {
    await run('scan', async () => {
      const result = await setupApi.homeScan();
      setHomeScan(result);
    });
  }

  async function saveWhatsApp(event: FormEvent) {
    event.preventDefault();
    if (!providerDone && !endpoint.trim()) return;
    await run('provider', async () => {
      await setupApi.saveProvider({
        provider_key: 'whatsapp',
        provider_type: 'waha',
        display_name: 'WhatsApp',
        enabled: true,
        endpoint: endpoint.trim(),
        session: session.trim() || 'default',
        engine,
        secret_value: wahaApiKey.trim() || undefined,
        config: {},
      });
      setWahaApiKey('');
    });
  }

  async function saveAI(event: FormEvent) {
    event.preventDefault();
    if (!aiModel.trim() || (!aiDone && !aiEndpoint.trim())) return;
    const providerKey = snapshot?.ai.active_provider || 'ai:primary';
    await run('ai', async () => {
      await setupApi.saveAIProvider({
        provider_key: providerKey,
        provider_type: 'openai-compatible',
        display_name: aiDisplayName.trim() || 'Primary AI',
        endpoint: aiEndpoint.trim(),
        model: aiModel.trim(),
        secret_value: aiApiKey.trim() || undefined,
        enabled: true,
        capabilities: ['intent'],
        config: {},
      });
      await setupApi.selectAIProvider(providerKey);
      setAiApiKey('');
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

  const missingText = (snapshot?.setup.missing_steps ?? [])
    .map((item) => MISSING_LABELS[item] ?? item)
    .join(', ');

  return (
    <>
      <PageHeader
        title="הגדרת Bobi Next"
        description="מתקינים, סורקים את Home Assistant, מחברים WhatsApp ו-AI ומגדירים משתמשים — בלי Scripts, Helpers או Entity IDs ידניים."
        action={
          <Badge tone={completed ? 'ok' : ready ? 'warning' : 'muted'} dot>
            {completed ? 'הוגדר' : ready ? 'מוכן לסיום' : 'בתהליך'}
          </Badge>
        }
      />

      <div className="mb-4 flex flex-wrap gap-2">
        <StepBadge done={homeDone}>Home Assistant</StepBadge>
        <StepBadge done={providerDone}>WhatsApp</StepBadge>
        <StepBadge done={aiDone}>AI</StepBadge>
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
              title="1. סריקת Home Assistant"
              description="Bobi קורא את ה-Device/Entity/Area Registry ואת היכולות החיות ישירות דרך Home Assistant. אין צורך ב-Token ידני, Scripts או Helpers."
              action={homeDone ? <Badge tone="ok">נסרק</Badge> : <Badge tone="muted">אוטומטי</Badge>}
            />
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <button className={primaryButton} disabled={busy !== ''} onClick={() => void scanHome()} type="button">
                <Search size={15} className="me-1 inline" />
                {busy === 'scan' ? 'סורק…' : homeDone ? 'סרוק שוב' : 'סרוק את הבית'}
              </button>
              <span className="text-xs text-slate-500 dark:text-slate-400">
                הסריקה היא לקריאה בלבד ואינה משנה שום מכשיר.
              </span>
            </div>
            {homeScan ? (
              <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
                <ScanMetric label="מכשירים" value={homeScan.devices} />
                <ScanMetric label="זמינים עכשיו" value={homeScan.available_devices} />
                <ScanMetric label="ישויות" value={homeScan.entities} />
                <ScanMetric label="אזורים" value={homeScan.areas} />
                <ScanMetric label="יכולות" value={homeScan.capabilities} />
              </div>
            ) : null}
          </Card>

          <Card as="section">
            <CardHeader
              icon={<MessageCircle size={20} />}
              title="2. WhatsApp"
              description="מחברים את WAHA. פרטי גישה נשמרים מוצפנים; אם כבר הוגדר מפתח אפשר להשאיר אותו ריק ולא לשנות אותו."
              action={providerDone ? <Badge tone="ok">מוכן</Badge> : undefined}
            />
            <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={(event) => void saveWhatsApp(event)}>
              <label className="text-sm text-slate-600 dark:text-slate-300 sm:col-span-2">
                כתובת WAHA
                <input
                  className={inputClass}
                  value={endpoint}
                  onChange={(event) => setEndpoint(event.target.value)}
                  placeholder={providerDone ? 'כבר נשמרה — השאירי ריק כדי לא לשנות' : 'http://waha:3000'}
                  required={!providerDone}
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
              <label className="text-sm text-slate-600 dark:text-slate-300 sm:col-span-2">
                WAHA API key — אופציונלי
                <input
                  autoComplete="new-password"
                  className={inputClass}
                  type="password"
                  value={wahaApiKey}
                  onChange={(event) => setWahaApiKey(event.target.value)}
                  placeholder={provider?.has_secret_ref ? 'מפתח כבר שמור — השאירי ריק כדי לשמור אותו' : 'אם WAHA מוגן במפתח, הזיני אותו כאן'}
                />
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
              icon={<Cpu size={20} />}
              title="3. AI"
              description="Bobi משתמש בספק OpenAI-compatible להבנת שפה בלבד; ה-AI אינו מקבל הרשאה לבצע פעולות ב-Home Assistant."
              action={aiDone ? <Badge tone="ok">{activeAI?.display_name || 'מוכן'}</Badge> : undefined}
            />
            <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={(event) => void saveAI(event)}>
              <label className="text-sm text-slate-600 dark:text-slate-300">
                שם הספק
                <input
                  className={inputClass}
                  value={aiDisplayName}
                  onChange={(event) => setAiDisplayName(event.target.value)}
                  placeholder="לדוגמה: OpenAI / Groq / Local AI"
                  required
                />
              </label>
              <label className="text-sm text-slate-600 dark:text-slate-300">
                מודל
                <input
                  className={inputClass}
                  value={aiModel}
                  onChange={(event) => setAiModel(event.target.value)}
                  placeholder="שם המודל אצל הספק"
                  required
                />
              </label>
              <label className="text-sm text-slate-600 dark:text-slate-300 sm:col-span-2">
                API endpoint
                <input
                  className={inputClass}
                  value={aiEndpoint}
                  onChange={(event) => setAiEndpoint(event.target.value)}
                  placeholder={aiDone ? 'כבר נשמר — השאירי ריק כדי לא לשנות' : 'https://…/v1'}
                  required={!aiDone}
                />
              </label>
              <label className="text-sm text-slate-600 dark:text-slate-300 sm:col-span-2">
                API key
                <input
                  autoComplete="new-password"
                  className={inputClass}
                  type="password"
                  value={aiApiKey}
                  onChange={(event) => setAiApiKey(event.target.value)}
                  placeholder={activeAI?.has_secret_ref ? 'מפתח כבר שמור — השאירי ריק כדי לשמור אותו' : 'המפתח מוצפן מיד ואינו מוחזר לדפדפן'}
                />
              </label>
              <div className="sm:col-span-2">
                <button className={primaryButton} disabled={busy !== ''} type="submit">
                  {busy === 'ai' ? 'שומר ובוחר…' : aiDone ? 'עדכן AI' : 'שמור ובחר AI'}
                </button>
              </div>
            </form>
          </Card>

          <Card as="section">
            <CardHeader
              icon={<UserRound size={20} />}
              title="4. משתמשים"
              description="כל אדם מקבל זהות Bobi יציבה, זיכרון והרשאות משלו."
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
              title="5. קישור WhatsApp והרשאה"
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

          <Card as="section" className={ready && homeDone ? 'border-emerald-200 dark:border-emerald-900/50' : undefined}>
            <CardHeader
              icon={<CheckCircle2 size={20} />}
              title="סיום"
              description={
                completed
                  ? 'ההגדרה הושלמה.'
                  : !homeDone
                    ? 'לפני הסיום יש להריץ סריקת Home Assistant מוצלחת.'
                    : ready
                      ? 'כל דרישות ההתקנה הושלמו. Bobi מוכן לשלב בדיקות ה-Shadow.'
                      : `עדיין חסר: ${missingText || 'טעינת נתונים'}`
              }
              action={completed ? <Badge tone="ok">מוכן</Badge> : undefined}
            />
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                className={primaryButton}
                disabled={!ready || !homeDone || busy !== '' || completed}
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
