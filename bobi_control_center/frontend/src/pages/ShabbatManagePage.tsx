/**
 * The Shabbat clock, as an editor rather than a report.
 *
 * Timings, profile membership and air-conditioner temperatures all arrive from
 * `bobi_cc_shabbat` as items with their own limits — the minutes before candle
 * lighting come with a range and a step, the profile lists come with the device
 * tokens they may hold, the temperatures come with the range that device
 * accepts. This screen renders those; it does not know that 16–30 is a sensible
 * temperature, and it must not, because the next air conditioner might differ.
 *
 * Saving here changes the schedule and nothing else. No device is switched on
 * or off by pressing save, and the preview dialog says so in as many words.
 */

import { Card } from '@/components/ui/Card';
import { Chip } from '@/components/ui/Field';
import { ManagedResourcePage } from '@/features/manage/ManagedResourcePage';
import { ResourceEditor } from '@/features/manage/ResourceEditor';
import type { ManagedItem } from '@/types/api';

const isProfile = (item: ManagedItem) => item.kind === 'list';

/**
 * A profile's membership, as chips.
 *
 * Clicking one stages the whole new list — membership is a set, and sending a
 * single token would leave Home Assistant guessing whether it was an addition
 * or a replacement.
 */
function Membership({
  item,
  onChange,
  writesEnabled,
}: {
  item: ManagedItem;
  onChange: (item: ManagedItem, value: unknown, operation?: string) => void;
  writesEnabled: boolean;
}) {
  const members = Array.isArray(item.value) ? (item.value as string[]).map(String) : [];
  const allowed = item.constraints?.allowed ?? [];
  const operable = writesEnabled && item.controllable && allowed.length > 0;

  if (allowed.length === 0) {
    return (
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
        {members.length > 0 ? members.join(' · ') : 'אין מכשירים בפרופיל.'}
      </p>
    );
  }

  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {allowed.map((option) => {
        const selected = members.includes(option.value);
        return (
          <Chip
            key={option.value}
            selected={selected}
            label={`${option.label} — ${selected ? 'בפרופיל' : 'לא בפרופיל'}`}
            onClick={() => {
              if (!operable) return;
              const next = selected
                ? members.filter((member) => member !== option.value)
                : [...members, option.value];
              onChange(item, next, 'set_membership');
            }}
          >
            {option.label}
          </Chip>
        );
      })}
    </div>
  );
}

export function ShabbatManagePage() {
  return (
    <ManagedResourcePage
      resource="shabbat"
      title="שעון שבת"
      description="תזמונים, מה נדלק ומה נכבה, וטמפרטורות."
      intro={
        <Card>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            עריכה כאן משנה את לוח הזמנים בלבד. שום מכשיר לא יידלק ולא יכובה בזמן השמירה.
          </p>
        </Card>
      }
    >
      {({ snapshot, request, writesEnabled }) => (
        <div className="space-y-4">
          <ResourceEditor
            snapshot={snapshot}
            onChange={request}
            writesEnabled={writesEnabled}
            filter={(item) => !isProfile(item)}
            emptyLabel="בובי לא פרסם תזמוני שבת."
          />
          {snapshot.items.filter(isProfile).map((item) => (
            <Card key={item.id}>
              <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                {item.label}
              </p>
              {item.description ? (
                <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                  {item.description}
                </p>
              ) : null}
              <Membership item={item} onChange={request} writesEnabled={writesEnabled} />
            </Card>
          ))}
        </div>
      )}
    </ManagedResourcePage>
  );
}
