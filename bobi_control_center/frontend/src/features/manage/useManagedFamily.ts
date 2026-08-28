/**
 * One managed family, ready to attach controls to anything on a page.
 *
 * `ManagedSection` renders a family as its own block, which suits a screen
 * whose controls belong together. A catalogue does not: a light's switch
 * belongs on the light's card, next to its name and its room, not in a second
 * list further down that repeats every device by name.
 *
 * So the wiring lives here — contract, snapshot, change flow — and both use it.
 * The rules it enforces are the same either way, and they are enforced once:
 *
 * * a family the contract does not declare has no controls;
 * * a family whose contract names no operation has no controls;
 * * an item the bridge did not mark controllable has no control;
 * * nothing is applied on click — every change goes through preview, explicit
 *   confirmation and commit.
 */

import { useMemo } from 'react';

import { useManagedChange } from './useManagedChange';
import { keys, useManagementContract, useResourceSnapshot } from '@/hooks/queries';
import type { ManagedItem, ManagedResource, ResourceSnapshot } from '@/types/api';

export interface ManagedFamily {
  /** The contract declared this family and its snapshot bridge answered. */
  available: boolean;
  snapshot: ResourceSnapshot | undefined;
  /** Every item the bridge published, by its canonical id. */
  itemsById: Map<string, ManagedItem>;
  /** The contract named at least one operation — a commit bridge exists. */
  hasWriteBridge: boolean;
  /** …and Home Assistant's master switch is on. */
  writesEnabled: boolean;
  /** Ask the backend to describe a change. Never writes. */
  request: (item: ManagedItem, value: unknown, operation?: string) => void;
  /**
   * Ask, and apply at once when the backend asks for no confirmation.
   *
   * For a switch on a catalogue: flipping a light is not a decision anybody
   * wants read back to them first. Whether a change may skip the dialog is the
   * preview's own answer, so a destructive one still stops and asks.
   */
  applyNow: (item: ManagedItem, value: unknown, operation?: string) => void;
  change: ReturnType<typeof useManagedChange>;
}

export function useManagedFamily(resource: ManagedResource): ManagedFamily {
  const contract = useManagementContract();
  const declared = (contract.data?.resources ?? []).find((entry) => entry.id === resource);
  const available = Boolean(declared?.available);
  const query = useResourceSnapshot(resource, available);
  const change = useManagedChange(resource, [keys.resource(resource), keys.audit]);

  const itemsById = useMemo(() => {
    const map = new Map<string, ManagedItem>();
    for (const item of query.data?.items ?? []) map.set(item.id, item);
    return map;
  }, [query.data]);

  const hasWriteBridge = (declared?.operations.length ?? 0) > 0;

  // The operation comes from what the bridge advertised for this item. An
  // item with none is not operable and never gets a control; this is the
  // second lock on the same door.
  const describe = (item: ManagedItem, value: unknown, operation?: string) => {
    const chosen = operation ?? item.primary_operation ?? item.operations[0];
    if (!chosen) return null;
    return { operation: chosen, resource_id: item.id, payload: { value } };
  };

  const request = (item: ManagedItem, value: unknown, operation?: string) => {
    const asked = describe(item, value, operation);
    if (asked) void change.start(asked);
  };

  const applyNow = (item: ManagedItem, value: unknown, operation?: string) => {
    const asked = describe(item, value, operation);
    if (asked) void change.startAndApply(asked);
  };

  return {
    available: available && Boolean(query.data?.available),
    snapshot: query.data,
    itemsById,
    hasWriteBridge,
    writesEnabled: (contract.data?.writes_enabled ?? false) && hasWriteBridge,
    request,
    applyNow,
    change,
  };
}

/**
 * Whether this item may be operated right now, and by which verb.
 *
 * Fail closed on every count: the bridge has to have marked it controllable,
 * named an operation on it, and — unless it is an `action`, which holds no
 * value — reported a current value to bind a preview to. A `readonly` kind is
 * the backend saying it could not tell how the item is edited, so it gets no
 * control here either, whatever else the bridge advertised on it.
 */
export function operableWith(
  item: ManagedItem | undefined,
  writesEnabled: boolean,
): string | null {
  if (!item || !writesEnabled) return null;
  if (item.kind === 'readonly') return null;
  if (!item.controllable || item.operations.length === 0) return null;
  if (item.kind !== 'action' && (item.value === null || item.value === undefined)) return null;
  return item.primary_operation ?? item.operations[0] ?? null;
}
