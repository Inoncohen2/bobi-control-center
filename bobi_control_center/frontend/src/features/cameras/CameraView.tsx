/**
 * A camera's picture, and nothing you can press to change the camera.
 *
 * The picture is fetched from this application, not from Home Assistant: the
 * `src` names the camera's **canonical id**, the backend resolves it and
 * fetches the bytes with its own credential, and the browser never holds an
 * entity id or a token. That is why this is an ordinary `<img>` pointing at our
 * own API rather than at Home Assistant's `entity_picture`, whose URL carries a
 * working access token for the stream.
 *
 * ## Two deliberate omissions
 *
 * **No power control.** Not disabled, not hidden behind a role — absent. This
 * component takes no change handler, so there is nothing here for a future
 * contract to switch on, which is the same promise the cameras screen makes by
 * passing `readOnly`.
 *
 * **No polling.** Every refresh costs a bridge call and a frame fetch, and the
 * house's rule is that polling stays modest. The picture loads on entry and
 * reloads when a person asks for it, so a screen left open overnight does not
 * quietly become the busiest thing in the house.
 */

import { useState } from 'react';
import { RefreshCw, VideoOff } from 'lucide-react';

import { apiUrl } from '@/api/client';
import { Button } from '@/components/ui/Button';

export function cameraSnapshotUrl(cameraId: string, attempt: number): string {
  // The counter is what makes a reload a reload: the response is `no-store`,
  // but a browser that has already painted this exact URL has no reason to ask
  // again, and a still frame that never changes is worse than no frame.
  return apiUrl(
    `/api/bobi/cameras/${encodeURIComponent(cameraId)}/snapshot?v=${attempt}`,
  );
}

export function CameraView({ cameraId, label }: { cameraId: string; label: string }) {
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const retry = () => {
    setFailed(false);
    setLoaded(false);
    setAttempt((n) => n + 1);
  };

  return (
    <div className="mt-2">
      <div className="relative overflow-hidden rounded-lg bg-slate-800 aspect-video">
        {failed ? (
          // The install this was written against answers 500 for this camera
          // every time, because it is unplugged. Saying so is the whole job:
          // a broken image icon would read as a bug in the app.
          <div className="flex h-full flex-col items-center justify-center gap-2 p-4 text-center">
            <VideoOff aria-hidden className="h-6 w-6 text-slate-400" />
            <p className="text-sm text-slate-300">המצלמה אינה זמינה כרגע</p>
            <p className="text-xs text-slate-400">
              בובי לא מדליק מצלמה כדי לבדוק אותה.
            </p>
          </div>
        ) : (
          <img
            key={attempt}
            src={cameraSnapshotUrl(cameraId, attempt)}
            alt={`תמונה חיה מ${label}`}
            className="h-full w-full object-cover"
            onError={() => setFailed(true)}
            onLoad={() => setLoaded(true)}
          />
        )}
        {!failed && !loaded ? (
          <p className="absolute inset-0 flex items-center justify-center text-sm text-slate-300">
            טוען תמונה…
          </p>
        ) : null}
      </div>

      <Button variant="ghost" className="mt-1.5 w-full" onClick={retry}>
        <RefreshCw aria-hidden className="ml-1.5 h-3.5 w-3.5" />
        {failed ? 'נסה שוב' : 'רענן תמונה'}
      </Button>
    </div>
  );
}
