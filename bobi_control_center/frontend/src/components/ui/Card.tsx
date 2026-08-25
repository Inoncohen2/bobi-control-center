import type { ReactNode } from 'react';
import { cn } from '@/utils/cn';

interface CardProps {
  children: ReactNode;
  className?: string;
  /** Adds hover lift. Use only when the whole card is clickable. */
  interactive?: boolean;
  as?: 'div' | 'article' | 'section' | 'li';
}

export function Card({ children, className, interactive = false, as: Tag = 'div' }: CardProps) {
  return (
    <Tag
      className={cn(
        'rounded-2xl border border-slate-200/80 bg-white p-5 shadow-card',
        'dark:border-slate-700/60 dark:bg-slate-800/60',
        interactive &&
          'transition-shadow hover:shadow-lift focus-within:ring-2 focus-within:ring-bobi-500/40',
        className,
      )}
    >
      {children}
    </Tag>
  );
}

interface CardHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function CardHeader({ title, description, icon, action, className }: CardHeaderProps) {
  return (
    <div className={cn('flex items-start gap-3', className)}>
      {icon ? (
        <span
          aria-hidden="true"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-bobi-50 text-bobi-600 dark:bg-bobi-500/15 dark:text-bobi-300"
        >
          {icon}
        </span>
      ) : null}
      <div className="min-w-0 flex-1">
        <h3 className="truncate text-base font-semibold text-slate-900 dark:text-slate-100">
          {title}
        </h3>
        {description ? (
          <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{description}</p>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function SectionTitle({
  children,
  action,
}: {
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{children}</h2>
      {action}
    </div>
  );
}
