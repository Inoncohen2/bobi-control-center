import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react';
import { useId } from 'react';
import { cn } from '@/utils/cn';

const CONTROL_CLASSES =
  'w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 ' +
  'placeholder:text-slate-400 focus:border-bobi-500 focus:outline-none focus:ring-2 focus:ring-bobi-500/30 ' +
  'disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500 ' +
  'dark:border-slate-600 dark:bg-slate-900/40 dark:text-slate-100 dark:disabled:bg-slate-800';

export function Label({ htmlFor, children }: { htmlFor: string; children: ReactNode }) {
  return (
    <label
      htmlFor={htmlFor}
      className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300"
    >
      {children}
    </label>
  );
}

interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  help?: string;
}

export function TextField({ label, help, className, id, ...rest }: TextFieldProps) {
  const generated = useId();
  const fieldId = id ?? generated;
  const helpId = help ? `${fieldId}-help` : undefined;

  return (
    <div className={className}>
      <Label htmlFor={fieldId}>{label}</Label>
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
}

export function SelectField({
  label,
  options,
  help,
  className,
  id,
  ...rest
}: SelectFieldProps) {
  const generated = useId();
  const fieldId = id ?? generated;
  const helpId = help ? `${fieldId}-help` : undefined;

  return (
    <div className={className}>
      <Label htmlFor={fieldId}>{label}</Label>
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

/** A `type="time"` input keeps native pickers on iOS. */
export function TimeField(props: Omit<TextFieldProps, 'type'>) {
  return <TextField type="time" {...props} />;
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
