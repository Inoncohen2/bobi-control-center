/**
 * The shell every managed family's screen sits in.
 *
 * It owns the four states a family can be in, so no individual page has to
 * remember them and none can accidentally skip one:
 *
 * * **No write bridge.** Home Assistant has not declared management at all.
 * * **This family is not in the bridge yet.** The contract knows about
 *   management but does not name this family, or its snapshot service answers
 *   unavailable. Shown as a fact about Home Assistant, with the reason it gave.
 * * **Writes are off.** Everything reads, previews work, commits refuse. This
 *   is presented as a switch that is off — never as a connection failure,
 *   because nothing is broken.
 * * **Ready.** Controls appear, and every one of them goes through preview →
 *   confirm → commit.
 */

import type { ReactNode } from 'react';
import { Info, ShieldOff } from 'lucide-react';

import { Card } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { QueryBoundary } from '@/components/state/QueryBoundary';
import { ChangeDialog } from './ChangeDialog';
import { useManagedChange } from './useManagedChange';
import { keys, useManagementContract, useResourceSnapshot } from '@/hooks/queries';
import type { ManagedItem, ManagedResource, ResourceSnapshot } from '@/types/api';

export interface ManagedRenderProps {
  snapshot: ResourceSnapshot;
  /** Ask the backend to describe a change. Never writes. */
  request: (item: ManagedItem, value: unknown, operation?: string) => void;
  /** Start a change that is not about one existing item — creating something. */
  requestNew: (operation: string, payload: Record<string, unknown>) => void;
  writesEnabled: boolean;
}

export function ManagedResourcePage({
  resource,
  title,
  description,
  children,
  intro,
}: {
  resource: ManagedResource;
  title: string;
  description?: string;
  intro?: ReactNode;
  children: (props: ManagedRenderProps) => ReactNode;
}) {
  const contract = useManagementContract();
  // The contract is what says this family exists. Asking for a snapshot the
  // contract does not advertise would be a service call whose answer we
  // already know, so the query is not enabled until it does.
  const declared = (contract.data?.resources ?? []).find((entry) => entry.id === resource);
  const query = useResourceSnapshot(resource, Boolean(declared?.available));

  const change = useManagedChange(resource, [keys.resource(resource), keys.audit]);

  // Three separate yeses, and all three have to be given before a control is
  // drawn: Home Assistant's master switch is on, the contract named at least
  // one operation for this family (so its commit bridge exists), and — per row
  // — the bridge marked that item controllable. A family announced with no
  // operations is exactly what a commit bridge still being written looks like
  // from here, and it gets values rather than a button that would 404.
  const hasWriteBridge = (declared?.operations.length ?? 0) > 0;
  const writesEnabled = (contract.data?.writes_enabled ?? false) && hasWriteBridge;

  const request = (item: ManagedItem, value: unknown, operation?: string) => {
    // The operation comes from what the bridge advertised for this item. An
    // item with none is not operable, and the editor never renders a control
    // for it — this guard is the second lock on the same door.
    const chosen = operation ?? item.operations[0];
    if (!chosen) return;
    void change.start({ operation: chosen, resource_id: item.id, payload: { value } });
  };
  const requestNew = (operation: string, payload: Record<string, unknown>) => {
    void change.start({ operation, resource_id: null, payload });
  };

  return (
    <div className="space-y-4">
      <PageHeader title={title} description={description} />
      {intro}

      {contract.data && !contract.data.available ? (
        <Notice
          icon={ShieldOff}
          title="ניהול עדיין לא הופעל ב-Home Assistant"
          body={contract.data.reason ?? undefined}
        />
      ) : null}

      {contract.data?.available && !declared?.available ? (
        <Notice
          icon={Info}
          title={`${title} — עדיין לא זמין לניהול`}
          body={
            declared?.detail ??
            'הגשר של בובי ב-Home Assistant עדיין לא כולל את המשאב הזה. ברגע שהוא יתווסף, המסך הזה יתמלא מעצמו.'
          }
        />
      ) : null}

      {declared?.available ? (
        <QueryBoundary
          isLoading={query.isLoading}
          error={query.error}
          data={query.data}
          errorMessage={`לא הצלחנו לטעון את ${title}`}
          onRetry={() => void query.refetch()}
        >
          {(snapshot) =>
            snapshot.available ? (
              <>
                {!hasWriteBridge ? (
                  <Notice
                    icon={Info}
                    title="קריאה בלבד"
                    body={
                      declared?.detail ??
                      'הגשר של בובי עדיין לא כולל פעולות כתיבה למשאב הזה. הנתונים מוצגים במלואם.'
                    }
                  />
                ) : !writesEnabled ? (
                  <Notice
                    icon={ShieldOff}
                    title="שינויים כבויים כרגע"
                    body="אפשר לראות הכול ולהריץ תצוגה מקדימה. ביצוע שינויים ייפתח כשיופעל המתג ב-Home Assistant."
                  />
                ) : null}
                {children({ snapshot, request, requestNew, writesEnabled })}
              </>
            ) : (
              <Notice
                icon={Info}
                title={`${title} — לא זמין`}
                body={snapshot.reason ?? undefined}
              />
            )
          }
        </QueryBoundary>
      ) : null}

      <ChangeDialog change={change} />
    </div>
  );
}

function Notice({
  icon: Icon,
  title,
  body,
}: {
  icon: typeof Info;
  title: string;
  body?: string;
}) {
  return (
    <Card>
      <div className="flex items-start gap-3">
        <Icon aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-slate-400" />
        <div className="min-w-0">
          <p className="text-sm font-medium text-slate-900 dark:text-slate-100">{title}</p>
          {body ? (
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{body}</p>
          ) : null}
        </div>
      </div>
    </Card>
  );
}
