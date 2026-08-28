/**
 * A switch that never guesses.
 *
 * Pressing it does not set the knob. It asks the backend, and the knob moves
 * only once a commit has been read back — the position on screen is Home
 * Assistant's answer, never an optimistic guess. That is why `pending` dims
 * rather than flips: a switch that slid over and slid back would be the
 * interface lying twice.
 *
 * What a press *leads to* depends on the caller and on the backend's own
 * judgement. On the device catalogue it previews and commits in one gesture,
 * because turning a light on is not a decision anybody wants read back to them
 * first; elsewhere it opens the confirmation dialog. Either way the preview
 * happens, and either way a change the backend called destructive stops and
 * asks. This component neither knows nor decides which — it reports a press.
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
      // The visible track is 52×28; a thumb needs 44 in both directions, so
      // only the height is short. The eight pixels are added above and below
      // by a pseudo-element rather than by padding, because padding would make
      // the element measure larger than it looks and push its row wide.
      //
      // Vertically only, and that matters: growing it sideways as well cost
      // nothing in layout but eight pixels in *scrollWidth*, which every
      // ancestor inherited — each row holding a switch reported itself 324px
      // wide inside a 316px card. It never reached the page, so nothing
      // scrolled and nothing looked wrong; it was a card quietly able to
      // scroll sideways for a hit area that was already wide enough.
      className={cn(
        'relative inline-flex h-7 w-[52px] shrink-0 items-center rounded-full transition-colors',
        "after:absolute after:-inset-y-2 after:inset-x-0 after:content-['']",
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2',
        'focus-visible:outline-bobi-600 disabled:cursor-not-allowed',
        pending && 'animate-pulse',
        disabled && 'opacity-40',
        on ? 'bg-bobi-600' : 'bg-slate-300 dark:bg-slate-600',
      )}
    >
      {/* `top-1` rather than a translate: the knob already uses translate for
          the slide, and two transforms on one element fight each other. */}
      <span
        aria-hidden="true"
        className={cn(
          'absolute right-1 top-1 h-5 w-5 rounded-full bg-white shadow-sm transition-transform',
          on ? '-translate-x-6' : 'translate-x-0',
        )}
      />
    </button>
  );
}
