/**
 * The cameras, as status rather than as a control panel.
 *
 * Cameras come from the same device snapshot as everything else, filtered to
 * the camera class. Two rules that are specific to them:
 *
 * * A powered-off camera is **not** switched on to find out how it is. Its
 *   status is whatever the bridge reported, and "off" is a status.
 * * **There is no power control here at all.** Not "unless the bridge says so"
 *   — none. The screen passes `readOnly`, so a `controllable` that turned true
 *   in a future contract cannot quietly grow a power button here.
 *
 * Since 3.15 each camera also shows its picture. That does not soften either
 * rule: the frame is a read, it is fetched by the backend so no entity id or
 * credential reaches the browser, and `CameraView` takes no change handler, so
 * the viewer has nothing to press that would reach the camera.
 */

import { Card } from '@/components/ui/Card';
import { CameraView } from '@/features/cameras/CameraView';
import { ManagedResourcePage } from '@/features/manage/ManagedResourcePage';
import { ResourceEditor } from '@/features/manage/ResourceEditor';
import { CAMERA_CLASS, DeviceDetail } from './DeviceControlPage';
import type { ManagedItem } from '@/types/api';

const isCamera = (item: ManagedItem) => String(item.detail.device_class ?? '') === CAMERA_CLASS;

export function CamerasPage() {
  return (
    <ManagedResourcePage
      resource="devices"
      title="מצלמות"
      description="איפה הן, ומה מצבן."
      intro={
        <Card>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            מצלמה כבויה נשארת כבויה. בובי לא מדליק מצלמה כדי לבדוק את מצבה.
          </p>
        </Card>
      }
    >
      {({ snapshot, request, writesEnabled }) => (
        <ResourceEditor
          snapshot={snapshot}
          onChange={request}
          writesEnabled={writesEnabled}
          readOnly
          filter={isCamera}
          renderDetail={(item) => (
            <>
              <DeviceDetail item={item} />
              <CameraView cameraId={item.id} label={item.label} />
            </>
          )}
          emptyLabel="בובי לא פרסם מצלמות."
        />
      )}
    </ManagedResourcePage>
  );
}
