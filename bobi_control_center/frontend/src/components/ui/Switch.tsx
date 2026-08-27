/**
 * A switch that asks before it acts.
 *
 * It looks like a switch and it moves like one, but pressing it does not change
 * anything: it asks the backend to describe the change, and the dialog that
 * follows is what commits. So the knob stays where the bridge says it is until
 * a commit has been read back — the position on screen is Home Assistant's
 * answer, never an optimistic guess.
 *
 * That is why `pending` dims rather than flips. A switch that slid over and
 * slid back would be the interface lying twice.
 */

import { cn } from '@/utils/cn';

export function Switch({
  on,
  label,
  onChange,
  pending = false,
  disabled = false,
}: {
  on: boolean;
  /** What is being switched, for a screen reader: "אור מטבח". */
  label: string;
  onChange: (next: boolean) => void;
  pending?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled || pending}
      onClick={(event) => {
        // The card behind this is itself a target; a tap on the switch is not
        // also a tap on the card.
        event.stopPropagation();
        onChange(!on);
      }}
      // The visible track is 28px tall; the target around it is 44, which is
      // the smallest a thumb reliably hits. The negative margin keeps the extra
      // eight pixels from pushing the card's layout around.
      className={cn(
        'group -m-2 inline-flex shrink-0 items-center justify-center p-2',
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2',
        'focus-visible:outline-bobi-600 disabled:cursor-not-allowed',
        disabled && 'opacity-40',
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          'relative inline-flex h-7 w-[52px] items-center rounded-full transition-colors',
          pending && 'animate-pulse',
          on ? 'bg-bobi-600' : 'bg-slate-300 dark:bg-slate-600',
        )}
      >
        <span
          className={cn(
            'absolute right-1 h-5 w-5 rounded-full bg-white shadow-sm transition-transform',
            on ? '-translate-x-6' : 'translate-x-0',
          )}
        />
      </span>
    </button>
  );
}
