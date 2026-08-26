/**
 * Bobi's settings — the morning summary, the home-status message, the Shabbat
 * alert, AI, Fast Paths.
 *
 * Every row on this page comes from `bobi_cc_settings_snapshot`. Nothing here
 * names an `input_boolean`, an `input_datetime` or any other Home Assistant
 * entity: the bridge publishes a setting with a label, a kind and its limits,
 * and this screen renders it. A setting the bridge stops publishing disappears
 * from the screen, which is the correct behaviour and not a bug to work around.
 */

import { ManagedResourcePage } from '@/features/manage/ManagedResourcePage';
import { ResourceEditor } from '@/features/manage/ResourceEditor';
import type { ManagedItem } from '@/types/api';

/** Notification rows live on their own screen; everything else belongs here. */
const notNotification = (item: ManagedItem) =>
  String(item.detail.notification_class ?? '') === '';

export function SettingsManagePage() {
  return (
    <ManagedResourcePage
      resource="settings"
      title="AI והגדרות"
      description="מה בובי שולח, מתי, ולמי."
    >
      {({ snapshot, request, writesEnabled }) => (
        <ResourceEditor
          snapshot={snapshot}
          onChange={request}
          writesEnabled={writesEnabled}
          filter={notNotification}
          emptyLabel="בובי לא פרסם הגדרות שניתן לשנות מכאן."
        />
      )}
    </ManagedResourcePage>
  );
}
