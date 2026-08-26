/**
 * The system screen: how Bobi is doing, and the few safe things to do about it.
 *
 * Only the actions the bridge advertises appear, and a fixed list is refused
 * whatever it advertises — restarting Home Assistant, updating the Supervisor,
 * deleting an integration or a device, restoring a backup. Those are not things
 * a household web page should be able to start, and the refusal lives in the
 * backend so it holds even if this screen were rewritten.
 */

import { Card } from '@/components/ui/Card';
import { ManagedResourcePage } from '@/features/manage/ManagedResourcePage';
import { ResourceEditor } from '@/features/manage/ResourceEditor';

export function SystemPage() {
  return (
    <ManagedResourcePage
      resource="system"
      title="מערכת"
      description="מצב בובי, ופעולות תחזוקה בטוחות."
      intro={
        <Card>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            פעולות כמו הפעלה מחדש של Home Assistant, עדכון Supervisor או שחזור גיבוי אינן
            מתבצעות מכאן — הן נעשות ישירות ב-Home Assistant.
          </p>
        </Card>
      }
    >
      {({ snapshot, request, writesEnabled }) => (
        <ResourceEditor
          snapshot={snapshot}
          onChange={request}
          writesEnabled={writesEnabled}
          emptyLabel="בובי לא פרסם פעולות מערכת."
        />
      )}
    </ManagedResourcePage>
  );
}
