import { FormEvent, ReactNode, useEffect, useState } from 'react';
import { LoaderCircle, LockKeyhole, LogOut, ShieldCheck } from 'lucide-react';

import { ApiError, api } from '@/api/client';

type AuthMode = 'home_assistant' | 'external';

interface AuthStatus {
  authenticated: boolean;
  mode: AuthMode;
  expires_in_seconds?: number;
}

interface Props {
  children: ReactNode;
}

export function ExternalAuthGate({ children }: Props) {
  const [mode, setMode] = useState<AuthMode | null>(null);
  const [password, setPassword] = useState('');
  const [checking, setChecking] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    let active = true;
    api
      .get<AuthStatus>('/api/auth/session')
      .then((status) => {
        if (active) setMode(status.mode);
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 401) {
          setMode(null);
          return;
        }
        setMessage(error instanceof ApiError ? error.message : 'לא הצלחנו לבדוק את החיבור');
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setMessage('');
    try {
      const status = await api.post<AuthStatus>('/api/auth/login', { password });
      setPassword('');
      setMode(status.mode);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : 'ההתחברות נכשלה');
    } finally {
      setSubmitting(false);
    }
  }

  async function logout() {
    setSubmitting(true);
    try {
      await api.post<AuthStatus>('/api/auth/logout');
      setMode(null);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : 'ההתנתקות נכשלה');
    } finally {
      setSubmitting(false);
    }
  }

  if (checking) {
    return (
      <main className="grid min-h-screen place-items-center bg-slate-950 text-white" dir="rtl">
        <div className="flex items-center gap-3 text-sm text-slate-300">
          <LoaderCircle className="h-5 w-5 animate-spin" />
          בודק חיבור מאובטח…
        </div>
      </main>
    );
  }

  if (mode === null) {
    return (
      <main
        className="grid min-h-screen place-items-center bg-gradient-to-br from-slate-950 via-slate-900 to-cyan-950 px-5 text-white"
        dir="rtl"
      >
        <section className="w-full max-w-sm rounded-3xl border border-white/10 bg-white/5 p-7 shadow-2xl backdrop-blur">
          <div className="mb-6 flex items-center gap-4">
            <div className="grid h-12 w-12 place-items-center rounded-2xl bg-cyan-400/15 text-cyan-300">
              <LockKeyhole className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-xl font-bold">כניסה ל־Bobi</h1>
              <p className="mt-1 text-sm text-slate-300">מרכז השליטה החיצוני המאובטח</p>
            </div>
          </div>

          <form className="space-y-4" onSubmit={submit}>
            <label className="block text-sm font-medium" htmlFor="bobi-password">
              סיסמה
            </label>
            <input
              autoComplete="current-password"
              autoFocus
              className="w-full rounded-xl border border-white/15 bg-slate-950/60 px-4 py-3 text-left outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20"
              dir="ltr"
              id="bobi-password"
              maxLength={512}
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              value={password}
            />
            {message ? (
              <p className="rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-200" role="alert">
                {message}
              </p>
            ) : null}
            <button
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-cyan-400 px-4 py-3 font-bold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={submitting || password.length === 0}
              type="submit"
            >
              {submitting ? <LoaderCircle className="h-5 w-5 animate-spin" /> : null}
              כניסה מאובטחת
            </button>
          </form>

          <p className="mt-5 flex items-center gap-2 text-xs leading-5 text-slate-400">
            <ShieldCheck className="h-4 w-4 shrink-0 text-emerald-400" />
            החיבור מוצפן, והגישה ל־Home Assistant נשארת בשרת בלבד.
          </p>
        </section>
      </main>
    );
  }

  return (
    <>
      {mode === 'external' ? (
        <button
          aria-label="התנתקות"
          className="fixed left-3 top-3 z-50 flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white/95 px-2.5 py-2 text-xs font-medium text-slate-600 shadow-sm backdrop-blur hover:text-slate-950 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900/95 dark:text-slate-300"
          disabled={submitting}
          onClick={logout}
          type="button"
        >
          <LogOut className="h-4 w-4" />
          התנתקות
        </button>
      ) : null}
      {children}
    </>
  );
}
