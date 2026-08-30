/**
 * A big, warm card with an accent — the household screens' unit of layout.
 *
 * `Card` is the neutral container the management screens are built from, and it
 * is right for a screen full of settings. It is wrong for the screens a family
 * actually opens: a shopping list and a room of lights are *places*, and a wall
 * of identical grey rectangles gives a person nothing to aim at.
 *
 * So a tile carries three things `Card` does not: a colour, an icon, and room.
 * The colour is per subject rather than per state — shopping is always amber,
 * reminders are always sky — so the household learns the screen by its shape
 * and stops reading the headings. It is deliberately *not* a status colour:
 * nothing here goes red when something is wrong, because a red that means "this
 * is the recipes list" and a red that means "this failed" cannot share a screen.
 *
 * The accent is a token, not a class string. Tailwind compiles the classes it
 * can see in the source, so a name assembled at runtime (`bg-${tone}-100`)
 * produces markup referring to CSS that was never generated — the card renders
 * with no colour at all and nothing reports a problem. Every class below is
 * written out in full for that reason.
 */

import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

import { cn } from '@/utils/cn';

export type TileTone = 'shopping' | 'recipes' | 'reminders' | 'family' | 'neutral';

interface ToneStyle {
  /** The icon chip: a filled circle carrying the subject's colour. */
  chip: string;
  /** A hairline down the leading edge, so the colour survives at a glance. */
  edge: string;
}

const TONES: Record<TileTone, ToneStyle> = {
  shopping: {
    chip: 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300',
    edge: 'bg-amber-400/70 dark:bg-amber-400/50',
  },
  recipes: {
    chip: 'bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300',
    edge: 'bg-rose-400/70 dark:bg-rose-400/50',
  },
  reminders: {
    chip: 'bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300',
    edge: 'bg-sky-400/70 dark:bg-sky-400/50',
  },
  family: {
    chip: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300',
    edge: 'bg-emerald-400/70 dark:bg-emerald-400/50',
  },
  neutral: {
    chip: 'bg-warm-200 text-warm-700 dark:bg-warm-800 dark:text-warm-200',
    edge: 'bg-warm-300 dark:bg-warm-700',
  },
};

export function Tile({
  title,
  icon: Icon,
  tone = 'neutral',
  count,
  children,
}: {
  title: string;
  icon: LucideIcon;
  tone?: TileTone;
  /**
   * How many things are on it. Rendered only when there are some: a family
   * list showing a grey "0" reads as a fault, and an empty list is not one.
   */
  count?: number;
  children: ReactNode;
}) {
  const style = TONES[tone];

  return (
    <section
      className={cn(
        'relative overflow-hidden rounded-3xl border border-warm-200/80 bg-white',
        'px-5 py-5 shadow-card transition-shadow hover:shadow-lift',
        'dark:border-warm-800/60 dark:bg-warm-900/40',
      )}
    >
      {/* Logical inset, so the edge follows the reading direction in RTL. */}
      <span aria-hidden className={cn('absolute inset-y-0 start-0 w-1.5', style.edge)} />

      <header className="mb-4 flex items-center gap-3">
        <span
          aria-hidden
          className={cn('grid h-11 w-11 shrink-0 place-items-center rounded-2xl', style.chip)}
        >
          <Icon className="h-5 w-5" />
        </span>
        <h2 className="text-lg font-semibold leading-tight text-warm-900 dark:text-warm-50">
          {title}
        </h2>
        {typeof count === 'number' && count > 0 ? (
          <span className="ms-auto rounded-full bg-warm-100 px-2.5 py-0.5 text-sm font-medium tabular-nums text-warm-700 dark:bg-warm-800 dark:text-warm-200">
            {count}
          </span>
        ) : null}
      </header>

      {children}
    </section>
  );
}
