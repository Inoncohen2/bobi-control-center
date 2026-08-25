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

  const commit = useCallback(
    async (confirmWord?: string) => {
      // A commit without a preview is a bug in the caller, not a request to
      // make one implicitly.
      if (!preview?.preview_id || !preview.valid) return;

      setStage('committing');
      setError(null);
      try {
        const response = await bobi.commitChange(resource, {
          preview_id: preview.preview_id,
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
      } catch (caught) {
        setError(caught as Error);
        setStage('preview');
      }
    },
    [resource, preview, invalidate, queryClient],
  );

  return { stage, preview, result, error, start, commit, reset };
}
