import { Link } from 'react-router-dom';
import { Compass } from 'lucide-react';

import { EmptyState } from '@/components/state/QueryBoundary';

export function NotFoundPage() {
  return (
    <div className="py-10">
      <EmptyState
        title="הדף הזה לא קיים"
        description="ייתכן שהקישור השתנה. אפשר לחזור למסך הבית."
        icon={<Compass size={32} />}
        action={
          <Link
            to="/"
            className="inline-flex h-10 items-center rounded-xl bg-bobi-600 px-4 text-sm font-medium text-white transition-colors hover:bg-bobi-700"
          >
            חזרה לבית
          </Link>
        }
      />
    </div>
  );
}
