/**
 * The write flow, as one state machine — and the only way a screen may change
 * anything.
 *
 *   idle → previewing → preview → committing → result
 *
 * Three rules are enforced here rather than in each page, so no screen can
 * accidentally opt out of them:
 *
 * 1. **A commit needs a preview.** `commit()` refuses unless a valid preview is
 *    in hand; the backend refuses too, and this only spares a pointless round
 *    trip.
 * 2. **A destructive change needs its word typed.** The button stays disabled
 *    until it matches what the preview asked for.
 * 3. **Nothing is optimistic.** The caller is told to refetch only after a
 *    result arrives, and the result distinguishes verified from unverified.
 *
 * ## Applying without a dialog
 *
 * Turning a light on is not a decision anybody wants read back to them first.
 * `startAndApply` previews and commits in one gesture — but the judgement of
 * *what may skip the dialog* is not made here and is not new: it is the
 * preview's own answer. A change the backend marked destructive, or for which
 * it asked for a typed word, always stops and shows the dialog.
 *
 * Nothing else is relaxed. The preview still happens, so the token, the
 * expected state and every published limit are still checked; the commit still
 * goes through the bridge, so the Home Assistant master switch and the
 * read-after-write verification still hold. What is removed is a question, not
 * a guard.
 *
 * And it is quiet only when it works: a commit that fails, or that comes back
 * unverified, opens the dialog to say so. Silence means the house agreed.
 */

import { useCallback, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import * as bobi from '@/api/bobi';
import { ApiError } from '@/api/client';
import type { CommitResponse, PreviewRequest, PreviewResponse } from '@/types/api';

export type ManageStage = 'idle' | 'previewing' | 'preview' | 'committing' | 'result';

export interface ManagedChange {
  stage: ManageStage;
  preview: PreviewResponse | null;
  result: CommitResponse | null;
  error: ApiError | Error | null;
  /** Ask the backend to describe a change. Never writes. */
  start: (request: PreviewRequest) => Promise<void>;
  /**
   * Preview and, if the backend asked for no confirmation, apply at once.
   *
   * Falls back to the dialog whenever the preview is invalid, destructive, or
   * wants a typed word — so a caller cannot use this to skip a confirmation
   * the backend asked for.
   */
  startAndApply: (request: PreviewRequest) => Promise<void>;
  /** Apply the previewed change. `confirmWord` is required when destructive. */
  commit: (confirmWord?: string) => Promise<void>;
  reset: () => void;
}

/**
 * @param resource The managed resource — `tasks` or `features`.
 * @param invalidate Query keys to refetch once a change has landed. Called
 *   only after a commit returns, so the screen never shows a value it has not
 *   read back from the bridge.
 */
export function useManagedChange(
  resource: string,
  invalidate: ReadonlyArray<readonly unknown[]> = [],
): ManagedChange {
  const queryClient = useQueryClient();
  const [stage, setStage] = useState<ManageStage>('idle');
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [result, setResult] = useState<CommitResponse | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);

  const reset = useCallback(() => {
    setStage('idle');
    setPreview(null);
    setResult(null);
    setError(null);
  }, []);

  const start = useCallback(
    async (request: PreviewRequest) => {
      setStage('previewing');
      setError(null);
      setResult(null);
      try {
        const response = await bobi.previewChange(resource, request);
        setPreview(response);
        setStage('preview');
      } catch (caught) {
        setError(caught as Error);
        setStage('idle');
      }
    },
    [resource],
  );

  /**
   * Commit against a preview held in hand rather than in state.
   *
   * `startAndApply` has its preview one tick before React does, and reading
   * the state here would commit against `null` — or, worse, against the
   * previous change's preview.
   */
  const applyTo = useCallback(
    async (approved: PreviewResponse, confirmWord?: string) => {
      setStage('committing');
      setError(null);
      try {
        const response = await bobi.commitChange(resource, {
          preview_id: approved.preview_id,
          confirmed: true,
          confirm_word: confirmWord ?? null,
        });
        setResult(response);
        setStage('result');
        // Refetch only now: the screen reflects what the bridge reports, not
        // what we hoped it would say.
        for (const key of invalidate) {
          void queryClient.invalidateQueries({ queryKey: key });
        }
        return response;
      } catch (caught) {
        setError(caught as Error);
        setStage('preview');
        return null;
      }
    },
    [resource, invalidate, queryClient],
  );

  const commit = useCallback(
    async (confirmWord?: string) => {
      // A commit without a preview is a bug in the caller, not a request to
      // make one implicitly.
      if (!preview?.preview_id || !preview.valid) return;
      await applyTo(preview, confirmWord);
    },
    [preview, applyTo],
  );

  const startAndApply = useCallback(
    async (request: PreviewRequest) => {
      setStage('previewing');
      setError(null);
      setResult(null);
      let response: PreviewResponse;
      try {
        response = await bobi.previewChange(resource, request);
      } catch (caught) {
        setError(caught as Error);
        setStage('idle');
        return;
      }
      setPreview(response);

      // The backend's own judgement, not a second one made here.
      const needsAsking = !response.valid || response.destructive || Boolean(response.confirm_word);
      if (needsAsking) {
        setStage('preview');
        return;
      }

      const outcome = await applyTo(response);
      // Quiet when it worked. A refusal or an unverified write keeps the
      // dialog open to say so — the one thing worse than a question is a
      // change that did not happen and did not mention it.
      // `committed` is the only status that means the bridge did it *and*
      // read it back. `committed_unverified` deliberately does not qualify:
      // the write may well have landed, and "may well have" is a thing to say
      // out loud rather than to close a dialog over.
      if (outcome?.result.status === 'committed') {
        reset();
      }
    },
    [resource, applyTo, reset],
  );

  return { stage, preview, result, error, start, startAndApply, commit, reset };
}
