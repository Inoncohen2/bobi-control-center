/**
 * The management half of a screen that already reads well without it.
 *
 * Devices, the Shabbat clock, rules and users all had good read-only screens
 * before management existed, and those screens still work — they come from the
 * Phase 2 read services, which are live today. This adds the controls under
 * them once Home Assistant declares the family, and renders **nothing at all**
 * until then.
 *
 * Nothing, deliberately. A standalone screen with no content has to explain why
 * it is empty; a section under a page full of information does not, and a
 * permanent "not available yet" banner on four screens would be four pieces of
 * furniture nobody can move.
 */

import type { ReactNode } from 'react';

import { Card, SectionTitle } from '@/components/ui/Card';
import { ChangeDialog } from './ChangeDialog';
import { useManagedChange } from './useManagedChange';
import { keys, useManagementContract, useResourceSnapshot } from '@/hooks/queries';
import type { ManagedItem, ManagedResource, ResourceSnapshot } from '@/types/api';

export function ManagedSection({
  resource,
  title,
  children,
}: {
  resource: ManagedResource;
  title: string;
  children: (props: {
    snapshot: ResourceSnapshot;
    request: (item: ManagedItem, value: unknown, operation?: string) => void;
    writesEnabled: boolean;
  }) => ReactNode;
}) {
  const contract = useManagementContract();
  const declared = (contract.data?.resources ?? []).find((entry) => entry.id === resource);
  const available = Boolean(declared?.available);
  const query = useResourceSnapshot(resource, available);
  const change = useManagedChange(resource, [keys.resource(resource), keys.audit]);

  const request = (item: ManagedItem, value: unknown, operation?: string) => {
    const chosen = operation ?? item.primary_operation ?? item.operations[0];
    if (!chosen) return;
    void change.start({ operation: chosen, resource_id: item.id, payload: { value } });
  };

  // A family with no operations in the contract has no commit bridge yet, so
  // it gets values and no save button.
  const hasWriteBridge = (declared?.operations.length ?? 0) > 0;
  const writesEnabled = (contract.data?.writes_enabled ?? false) && hasWriteBridge;

  if (!available || !query.data?.available) return null;

  return (
    <section className="space-y-3">
      <SectionTitle>{title}</SectionTitle>
      {!writesEnabled ? (
        <Card>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            {hasWriteBridge
              ? 'אפשר להריץ תצוגה מקדימה. ביצוע שינויים ייפתח כשיופעל המתג ב-Home Assistant.'
              : (declared?.detail ??
                'הגשר של בובי עדיין לא כולל פעולות כתיבה למשאב הזה. הנתונים מוצגים במלואם.')}
          </p>
        </Card>
      ) : null}
      {children({ snapshot: query.data, request, writesEnabled })}
      <ChangeDialog change={change} />
    </section>
  );
}
