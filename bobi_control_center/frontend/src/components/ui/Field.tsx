import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react';
import { useId } from 'react';
import { cn } from '@/utils/cn';

const CONTROL_CLASSES =
  'w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 ' +
  'placeholder:text-slate-400 focus:border-bobi-500 focus:outline-none focus:ring-2 focus:ring-bobi-500/30 ' +
  'disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500 ' +
  'dark:border-slate-600 dark:bg-slate-900/40 dark:text-slate-100 dark:disabled:bg-slate-800';

export function Label({
  htmlFor,
  children,
  srOnly = false,
}: {
  htmlFor: string;
  children: ReactNode;
  /**
   * Hide the label visually but keep it for a screen reader. For a control
   * whose row already carries its name — the generic resource editor puts the
   * label on the left and the control on the right — repeating it above the
   * field is noise on a phone and a duplicate to anyone listening.
   */
  srOnly?: boolean;
}) {
  return (
    <label
      htmlFor={htmlFor}
      className={cn(
        srOnly ? 'sr-only' : 'mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300',
      )}
    >
      {children}
    </label>
  );
}

interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  help?: string;
  srOnlyLabel?: boolean;
}

export function TextField({ label, help, className, id, srOnlyLabel, ...rest }: TextFieldProps) {
  const generated = useId();
  const fieldId = id ?? generated;
  const helpId = help ? `${fieldId}-help` : undefined;

  return (
    <div className={className}>
      <Label htmlFor={fieldId} srOnly={srOnlyLabel}>
        {label}
      </Label>
      <input id={fieldId} aria-describedby={helpId} className={CONTROL_CLASSES} {...rest} />
      {help ? (
        <p id={helpId} className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          {help}
        </p>
      ) : null}
    </div>
  );
}

interface SelectFieldProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  options: Array<{ value: string; label: string }>;
  help?: string;
  srOnlyLabel?: boolean;
}

export function SelectField({
  label,
  options,
  help,
  className,
  id,
  srOnlyLabel,
  ...rest
}: SelectFieldProps) {
  const generated = useId();
  const fieldId = id ?? generated;
  const helpId = help ? `${fieldId}-help` : undefined;

  return (
    <div className={className}>
      <Label htmlFor={fieldId} srOnly={srOnlyLabel}>
        {label}
      </Label>
      <select id={fieldId} aria-describedby={helpId} className={CONTROL_CLASSES} {...rest}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {help ? (
        <p id={helpId} className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          {help}
        </p>
      ) : null}
    </div>
  );
}

export function Chip({
  selected,
  onClick,
  children,
  label,
}: {
  selected: boolean;
  onClick: () => void;
  children: ReactNode;
  label?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      aria-label={label}
      className={cn(
        'rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors',
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-bobi-600',
        selected
          ? 'bg-bobi-600 text-white'
          : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-300 dark:hover:bg-slate-600',
      )}
    >
      {children}
    </button>
  );
}

/**
 * A time, on a 24-hour clock, whatever the browser thinks the locale is.
 *
 * `<input type="time">` looks right until you see it: the format of the *shown*
 * text comes from the browser's UI language, not from the page's `lang` and not
 * from anything a page can set. In a Hebrew, right-to-left, Israeli household
 * it rendered "11:30 PM" — and it kept rendering "11:30 PM" with the browser
 * locale forced to `he-IL`, because that setting does not reach this control.
 *
 * So the clock is built rather than borrowed. Two selects are not a downgrade
 * on a phone: iOS and Android both open a native wheel for a `<select>`, which
 * is the same gesture the time input gave, and the value is unambiguous in
 * every locale on earth.
 *
 * The value in and out stays `HH:MM` — the same string `<input type="time">`
 * held — so nothing upstream of this control has to know it changed.
 */
export function TimeField({
  label,
  value,
  onChange,
  help,
  className,
  srOnlyLabel,
  disabled,
}: {
  label: string;
  /** `HH:MM`. An unparseable value leaves both wheels empty rather than lying. */
  value: string;
  onChange: (next: string) => void;
  help?: string;
  className?: string;
  srOnlyLabel?: boolean;
  disabled?: boolean;
}) {
  const generated = useId();
  const helpId = help ? `${generated}-help` : undefined;
  const [hour = '', minute = ''] = /^\d{1,2}:\d{2}/.test(value)
    ? value.split(':').map((part) => part.padStart(2, '0'))
    : [];

  const emit = (nextHour: string, nextMinute: string) => {
    // Half a time is not a time. Until both wheels are set there is nothing
    // to preview, so nothing is emitted and the row stays as the bridge left it.
    if (!nextHour || !nextMinute) return;
    onChange(`${nextHour}:${nextMinute}`);
  };

  return (
    <div className={className}>
      <Label htmlFor={`${generated}-hour`} srOnly={srOnlyLabel}>
        {label}
      </Label>
      {/* `dir="ltr"`: a clock reads hours-then-minutes in every language. */}
      <div dir="ltr" className="flex items-center gap-1.5">
        <select
          id={`${generated}-hour`}
          aria-describedby={helpId}
          aria-label={`${label} — שעה`}
          value={hour}
          disabled={disabled}
          onChange={(event) => emit(event.target.value, minute || '00')}
          className={CONTROL_CLASSES}
        >
          {hour ? null : <option value="">--</option>}
          {HOURS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
        <span aria-hidden="true" className="text-lg font-semibold text-slate-400">
          :
        </span>
        <select
          aria-label={`${label} — דקות`}
          value={minute}
          disabled={disabled}
          onChange={(event) => emit(hour || '00', event.target.value)}
          className={CONTROL_CLASSES}
        >
          {minute ? null : <option value="">--</option>}
          {MINUTES.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </div>
      {help ? (
        <p id={helpId} className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          {help}
        </p>
      ) : null}
    </div>
  );
}

const HOURS = Array.from({ length: 24 }, (_, index) => String(index).padStart(2, '0'));
const MINUTES = Array.from({ length: 60 }, (_, index) => String(index).padStart(2, '0'));
