import { cn } from '@/utils/cn';

interface ToggleProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  /** Required: a switch with no accessible name is unusable. */
  label: string;
  disabled?: boolean;
  size?: 'sm' | 'md';
}

export function Toggle({ checked, onChange, label, disabled = false, size = 'md' }: ToggleProps) {
  const dimensions = size === 'sm' ? 'h-5 w-9' : 'h-6 w-11';
  const knob = size === 'sm' ? 'h-3.5 w-3.5' : 'h-5 w-5';
  // RTL: the knob starts on the right and travels leftwards when switched on.
  const offset = size === 'sm' ? '-translate-x-4' : '-translate-x-5';

  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex shrink-0 items-center rounded-full transition-colors',
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-bobi-600',
        dimensions,
        checked ? 'bg-bobi-600' : 'bg-slate-300 dark:bg-slate-600',
        disabled && 'cursor-not-allowed opacity-50',
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          'absolute right-0.5 rounded-full bg-white shadow transition-transform',
          knob,
          checked ? offset : 'translate-x-0',
        )}
      />
    </button>
  );
}
