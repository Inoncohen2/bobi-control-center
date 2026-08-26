/**
 * Household members and what they may do.
 *
 * The phone number is shown masked and never in full — the bridge sends a
 * `phone_masked` and the backend drops anything else that looks like a number
 * or a LID before it leaves the server. There is nothing on this screen that
 * could be un-masked by looking harder at the response.
 *
 * The last enabled admin cannot be disabled or demoted. The backend refuses it
 * before a preview exists and Home Assistant refuses it again; this screen only
 * shows the refusal in the dialog where the change was asked for.
 */

import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { ManagedResourcePage } from '@/features/manage/ManagedResourcePage';
import { ResourceEditor } from '@/features/manage/ResourceEditor';
import type { ManagedItem } from '@/types/api';

const ROLE_LABELS: Record<string, string> = {
  admin: 'מנהל',
  member: 'בן בית',
  guest: 'אורח',
};

function UserDetail({ item }: { item: ManagedItem }) {
  const role = String(item.detail.role ?? '');
  const masked = item.detail.phone_masked;
  const configured = (key: string) => item.detail[key] === true;

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      {role ? <Badge tone="info">{ROLE_LABELS[role] ?? role}</Badge> : null}
      <Badge tone={configured('whatsapp_configured') ? 'ok' : 'muted'}>
        {configured('whatsapp_configured') ? 'וואטסאפ מוגדר' : 'וואטסאפ לא מוגדר'}
      </Badge>
      <Badge tone={configured('calendar_configured') ? 'ok' : 'muted'}>
        {configured('calendar_configured') ? 'יומן מוגדר' : 'יומן לא מוגדר'}
      </Badge>
      <Badge tone={configured('task_list_configured') ? 'ok' : 'muted'}>
        {configured('task_list_configured') ? 'רשימת משימות' : 'אין רשימת משימות'}
      </Badge>
      {typeof masked === 'string' && masked ? (
        <Badge tone="neutral">{masked}</Badge>
      ) : null}
    </div>
  );
}

export function UsersManagePage() {
  return (
    <ManagedResourcePage
      resource="users"
      title="משתמשים"
      description="מי מקבל מה, ומי רשאי לשנות."
      intro={
        <Card>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            מספרי הטלפון מוצגים ממוסכים תמיד. חייב להישאר לפחות מנהל אחד פעיל.
          </p>
        </Card>
      }
    >
      {({ snapshot, request, writesEnabled }) => (
        <ResourceEditor
          snapshot={snapshot}
          onChange={request}
          writesEnabled={writesEnabled}
          renderDetail={(item) => <UserDetail item={item} />}
          emptyLabel="בובי לא פרסם משתמשים לניהול."
        />
      )}
    </ManagedResourcePage>
  );
}
