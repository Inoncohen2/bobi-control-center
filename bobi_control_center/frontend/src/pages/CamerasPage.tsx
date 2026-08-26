/**
 * The cameras, as status rather than as a control panel.
 *
 * Cameras come from the same device snapshot as everything else, filtered to
 * the camera class. Two rules that are specific to them:
 *
 * * A powered-off camera is **not** switched on to find out how it is. Its
 *   status is whatever the bridge reported, and "off" is a status.
 * * A power control appears only if the bridge explicitly marked the camera
 *   controllable and named the operation. A camera is the one device where a
 *   stray control is worse than a missing one.
 */

import { Card } from '@/components/ui/Card';
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
          filter={isCamera}
          renderDetail={(item) => <DeviceDetail item={item} />}
          emptyLabel="בובי לא פרסם מצלמות."
        />
      )}
    </ManagedResourcePage>
  );
}
