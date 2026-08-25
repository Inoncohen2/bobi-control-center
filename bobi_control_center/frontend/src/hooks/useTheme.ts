import { useCallback, useEffect, useState } from 'react';

export type ThemeChoice = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'bobi.theme';

/**
 * Theme preference only — never a secret. `localStorage` is used exclusively
 * for this kind of harmless per-device UI state.
 */
function readStoredTheme(): ThemeChoice {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored;
  } catch {
    // Private mode or blocked storage — fall back to following the system.
  }
  return 'system';
}

function prefersDark(): boolean {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
}

export function useTheme() {
  const [choice, setChoice] = useState<ThemeChoice>(readStoredTheme);

  const apply = useCallback((next: ThemeChoice) => {
    const dark = next === 'dark' || (next === 'system' && prefersDark());
    document.documentElement.classList.toggle('dark', dark);
  }, []);

  useEffect(() => {
    apply(choice);
    try {
      localStorage.setItem(STORAGE_KEY, choice);
    } catch {
      // Not being able to remember the choice is not worth an error.
    }
  }, [choice, apply]);

  useEffect(() => {
    if (choice !== 'system') return undefined;
    const media = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!media) return undefined;

    const onChange = () => apply('system');
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, [choice, apply]);

  return { theme: choice, setTheme: setChoice };
}
