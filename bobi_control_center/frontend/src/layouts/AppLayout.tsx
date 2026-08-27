/**
 * The app shell.
 *
 * Desktop: a persistent sidebar on the right (correct side for RTL).
 * Mobile:  a bottom bar with the four primary destinations plus "עוד",
 *          with safe-area padding so it clears the iPhone home indicator.
 */

import { useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { MoreHorizontal, Moon, Sun, SunMoon, X } from 'lucide-react';

import { cn } from '@/utils/cn';
import { useTheme, type ThemeChoice } from '@/hooks/useTheme';
import { IconButton } from '@/components/ui/Button';
import { NAV_ITEMS, PRIMARY_NAV, SECONDARY_NAV } from './navigation';

const THEME_ORDER: ThemeChoice[] = ['system', 'light', 'dark'];
const THEME_LABELS: Record<ThemeChoice, string> = {
  system: 'לפי המערכת',
  light: 'מצב בהיר',
  dark: 'מצב כהה',
};

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const next = THEME_ORDER[(THEME_ORDER.indexOf(theme) + 1) % THEME_ORDER.length] as ThemeChoice;
  const Icon = theme === 'dark' ? Moon : theme === 'light' ? Sun : SunMoon;

  return (
    <IconButton
      label={`ערכת נושא: ${THEME_LABELS[theme]}. מעבר ל${THEME_LABELS[next]}`}
      icon={<Icon size={18} />}
      onClick={() => setTheme(next)}
    />
  );
}

function BobiMark() {
  return (
    <div className="flex items-center gap-2.5">
      <span
        aria-hidden="true"
        className="flex h-9 w-9 items-center justify-center rounded-2xl bg-bobi-600 text-lg"
      >
        🤖
      </span>
      <div className="leading-tight">
        <p className="font-semibold text-slate-900 dark:text-slate-100">בובי</p>
        <p className="text-xs text-slate-500 dark:text-slate-400">מרכז ניהול</p>
      </div>
    </div>
  );
}

const linkClasses = ({ isActive }: { isActive: boolean }) =>
  cn(
    'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors',
    'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-bobi-600',
    isActive
      ? 'bg-bobi-50 text-bobi-700 dark:bg-bobi-500/15 dark:text-bobi-300'
      : 'text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800',
  );

function Sidebar() {
  return (
    <aside className="hidden w-64 shrink-0 border-l border-slate-200 bg-white/70 px-4 py-5 lg:flex lg:flex-col dark:border-slate-700 dark:bg-slate-900/40">
      <div className="px-1 pb-5">
        <BobiMark />
      </div>
      <nav aria-label="ניווט ראשי" className="flex-1 space-y-1 overflow-y-auto">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} end={to === '/'} className={linkClasses}>
            <Icon aria-hidden="true" size={18} />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-slate-200 pt-3 dark:border-slate-700">
        <p className="px-3 text-xs text-slate-400 dark:text-slate-500">
          מצב הדגמה · ללא חיבור אמיתי
        </p>
      </div>
    </aside>
  );
}

function MoreSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 lg:hidden">
      <button
        type="button"
        aria-label="סגירה"
        onClick={onClose}
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm"
      />
      <div className="absolute inset-x-0 bottom-0 rounded-t-3xl bg-white pb-[calc(env(safe-area-inset-bottom)+1rem)] pt-2 shadow-lift dark:bg-slate-800">
        <div className="flex items-center justify-between px-5 py-3">
          <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">עוד</h2>
          <IconButton label="סגירה" icon={<X size={18} />} onClick={onClose} />
        </div>
        <nav aria-label="ניווט נוסף" className="grid grid-cols-2 gap-2 px-4 pb-2">
          {SECONDARY_NAV.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} onClick={onClose} className={linkClasses}>
              <Icon aria-hidden="true" size={18} />
              {label}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}

function BottomNav({ onMore }: { onMore: () => void }) {
  const { pathname } = useLocation();
  const onSecondary = SECONDARY_NAV.some((item) => pathname.startsWith(item.to));

  return (
    <nav
      aria-label="ניווט ראשי"
      className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden dark:border-slate-700 dark:bg-slate-900/95"
    >
      {/* One column per destination plus one for "עוד". It was fixed at five
          while holding six, so the sixth wrapped onto a second row and ate a
          thumb's worth of screen on every page. Deriving the count means adding
          a primary destination can never quietly do that again. */}
      <ul
        className="grid"
        style={{ gridTemplateColumns: `repeat(${PRIMARY_NAV.length + 1}, minmax(0, 1fr))` }}
      >
        {PRIMARY_NAV.map(({ to, label, icon: Icon }) => (
          <li key={to} className="min-w-0">
            <NavLink
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                cn(
                  'flex min-w-0 flex-col items-center gap-1 px-0.5 pb-1.5 pt-2',
                  'text-[10px] font-medium leading-none transition-colors',
                  isActive
                    ? 'text-bobi-600 dark:text-bobi-400'
                    : 'text-slate-500 dark:text-slate-400',
                )
              }
            >
              {({ isActive }) => (
                <>
                  {/* A filled pill behind the active icon, so the current tab
                      reads at a glance without relying on colour alone. */}
                  <span
                    className={cn(
                      'flex h-7 w-12 items-center justify-center rounded-full transition-colors',
                      isActive ? 'bg-bobi-50 dark:bg-bobi-500/15' : 'bg-transparent',
                    )}
                  >
                    <Icon aria-hidden="true" size={19} />
                  </span>
                  <span className="w-full truncate text-center">{label}</span>
                </>
              )}
            </NavLink>
          </li>
        ))}
        <li className="min-w-0">
          <button
            type="button"
            onClick={onMore}
            aria-label="תפריט נוסף"
            className={cn(
              'flex w-full min-w-0 flex-col items-center gap-1 px-0.5 pb-1.5 pt-2',
              'text-[10px] font-medium leading-none transition-colors',
              onSecondary ? 'text-bobi-600 dark:text-bobi-400' : 'text-slate-500 dark:text-slate-400',
            )}
          >
            <span
              className={cn(
                'flex h-7 w-12 items-center justify-center rounded-full transition-colors',
                onSecondary ? 'bg-bobi-50 dark:bg-bobi-500/15' : 'bg-transparent',
              )}
            >
              <MoreHorizontal aria-hidden="true" size={19} />
            </span>
            <span className="w-full truncate text-center">עוד</span>
          </button>
        </li>
      </ul>
    </nav>
  );
}

export function AppLayout() {
  const [moreOpen, setMoreOpen] = useState(false);

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-900 dark:text-slate-100">
      <Sidebar />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-slate-200 bg-white/80 px-4 py-3 pt-[calc(env(safe-area-inset-top)+0.75rem)] backdrop-blur lg:px-8 dark:border-slate-700 dark:bg-slate-900/80">
          {/* The sidebar already carries the mark on a wide screen; repeating
              it in the header would be branding twice and saying nothing. */}
          <div className="lg:hidden">
            <BobiMark />
          </div>
          <div className="hidden lg:block" />
          <ThemeToggle />
        </header>

        <main
          id="main"
          className="mx-auto w-full max-w-5xl flex-1 px-4 py-5 pb-28 lg:px-8 lg:pb-10"
        >
          <Outlet />
        </main>
      </div>

      <BottomNav onMore={() => setMoreOpen(true)} />
      <MoreSheet open={moreOpen} onClose={() => setMoreOpen(false)} />
    </div>
  );
}
