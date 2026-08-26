/**
 * Smart notifications, and the event classes beside them.
 *
 * These are settings — they arrive from the same `bobi_cc_settings_snapshot`
 * as everything on the settings screen — but they are the settings a household
 * fiddles with most, so they get a screen of their own rather than a long
 * scroll under something else. The bridge marks them with a
 * `notification_class`, and that is the only thing this file knows about them.
 */

import { Card } from '@/components/ui/Card';
import { ManagedResourcePage } from '@/features/manage/ManagedResourcePage';
import { ResourceEditor } from '@/features/manage/ResourceEditor';
import type { ManagedItem } from '@/types/api';

const classOf = (item: ManagedItem) => String(item.detail.notification_class ?? '');
const isNotification = (item: ManagedItem) => classOf(item) !== '';

export function NotificationsPage() {
  return (
    <ManagedResourcePage
      resource="settings"
      title="התראות חכמות"
      description="מה בובי מודיע עליו, ולמי."
      intro={
        <Card>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            כל שינוי כאן עובר תצוגה מקדימה לפני ביצוע, ובובי קורא את המצב בחזרה כדי לוודא שהוא
            נקלט.
          </p>
        </Card>
      }
    >
      {({ snapshot, request, writesEnabled }) => (
        <ResourceEditor
          snapshot={snapshot}
          onChange={request}
          writesEnabled={writesEnabled}
          filter={isNotification}
          emptyLabel="בובי לא פרסם התראות שניתן לנהל מכאן."
        />
      )}
    </ManagedResourcePage>
  );
}
