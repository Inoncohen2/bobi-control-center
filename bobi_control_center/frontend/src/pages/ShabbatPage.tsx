import { Flame } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card, SectionTitle } from '@/components/ui/Card';
import { AdvancedDisclosure, TechnicalDetails } from '@/components/ui/Advanced';
import { PageHeader } from '@/components/ui/PageHeader';
import { EmptyState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useShabbat } from '@/hooks/queries';
import type { ManagedItem, ResourceSnapshot, ShabbatProfile } from '@/types/api';
import { ManagedSection } from '@/features/manage/ManagedSection';
import { useManagedFamily } from '@/features/manage/useManagedFamily';
import { ItemRow, ResourceEditor } from '@/features/manage/ResourceEditor';
import { ProfileEditor } from '@/features/shabbat/ProfileEditor';

/**
 * Profiles are rendered from the list the bridge defines, not a fixed four, so
 * a new profile kind appears without a frontend change. Each device arrives as
 * an id + label pair, already resolved from the bridge's own tokens by the
 * backend: the label is shown, and the token stays in the technical view.
 */
function ProfileCard({ profile }: { profile: ShabbatProfile }) {
  return (
    <Card as="li" className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 font-semibold text-slate-900 dark:text-slate-100">
          {profile.label}
        </h3>
        <Badge tone={profile.active === false ? 'muted' : 'ok'} dot>
          {profile.active === false ? 'לא פעיל' : 'פעיל'}
        </Badge>
      </div>

      <dl className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
        {profile.time ? (
          <div className="flex gap-1.5">
            <dt className="text-slate-500 dark:text-slate-400">שעה</dt>
            <dd className="font-medium tabular-nums text-slate-900 dark:text-slate-100">
              {profile.time}
            </dd>
          </div>
        ) : null}
        {profile.offset_minutes !== null ? (
          <div className="flex gap-1.5">
            <dt className="text-slate-500 dark:text-slate-400">היסט</dt>
            <dd className="font-medium text-slate-900 dark:text-slate-100">
              {profile.offset_minutes} דקות
            </dd>
          </div>
        ) : null}
      </dl>

      {profile.devices.length > 0 ? (
        <div>
          <p className="mb-1.5 text-sm text-slate-500 dark:text-slate-400">מכשירים</p>
          <div className="flex flex-wrap gap-1.5">
            {profile.devices.map((device) => (
              <Badge key={device.id} tone="info">
                {device.label}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}

      <AdvancedDisclosure title="פרטים טכניים">
        <TechnicalDetails
          source={profile as unknown as Record<string, unknown>}
          known={[
            ['kind', 'סוג פרופיל'],
            ['id', 'מזהה'],
          ]}
          extra={{
            ...profile.extra,
            // The bridge's own device tokens, which Phase 3 will write back.
            tokens: profile.devices.map((device) => device.id),
          }}
        />
      </AdvancedDisclosure>
    </Card>
  );
}

/**
 * "פרשת כי תבוא", without saying "פרשת" twice.
 *
 * The `jewish_calendar` sensor gives the bare name of the portion, so the word
 * belongs here — but a bridge that includes it should not produce
 * "פרשת פרשת ראה", which is what the test double did.
 */
function parashaTitle(parasha: string): string {
  const name = parasha.trim();
  return name.startsWith('פרשת') ? name : `פרשת ${name}`;
}

/**
 * One Shabbat time, big enough to read from across the kitchen.
 *
 * `tabular-nums` so 18:51 and 19:45 line up under each other. No bidi isolate:
 * a colon between two digit runs is a numeric separator, so "18:51" already
 * resolves left-to-right inside a right-to-left line. A range like "18:00–19:00"
 * does need one — the dash there separates two runs rather than joining one —
 * which is why the calendar has isolates and this does not.
 */
function ShabbatTime({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="rounded-2xl bg-white/70 px-3 py-2 text-center dark:bg-slate-900/40">
      <dt className="text-xs text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="mt-0.5 text-3xl font-bold tabular-nums text-slate-900 dark:text-slate-50">
        {value ?? '—'}
      </dd>
    </div>
  );
}

/**
 * Which timing row governs which profile.
 *
 * The bridge keeps the times in a group of their own, away from the profiles
 * they belong to, so a profile card has to be told where to look. The two
 * "before Shabbat" profiles share one offset — they both run a fixed number of
 * minutes before candle lighting — and that offset is edited once, in the
 * timing card, rather than twice under two headings where changing either
 * would silently change the other.
 */
const PROFILE_TIME: Record<string, string> = {
  night_off: 'night_off_time',
  morning_on: 'morning_on_time',
  extra_off: 'extra_off_time',
  extra_on: 'extra_on_time',
};

/**
 * The switch that decides whether a profile runs at all.
 *
 * Only the two extra clocks have one. The original four are the Shabbat the
 * household already keeps — they run, and what is editable is which devices
 * they touch. A clock that was added has to be able to sit at 00:00 doing
 * nothing until somebody sets it, so it carries its own switch, and that
 * switch belongs on the clock's own card rather than in a list of times where
 * it would read as one more hour to set.
 */
const PROFILE_ENABLED: Record<string, string> = {
  extra_off: 'extra_off_enabled',
  extra_on: 'extra_on_enabled',
};

/** A clock the household added, rather than one of the original four. */
const ADDED_CLOCK = new Set(['extra_off', 'extra_on']);

/** A profile that runs relative to candle lighting rather than at a set hour. */
const RELATIVE_TO_CANDLES = new Set(['pre_off', 'pre_on']);

/**
 * The managed Shabbat family, reassembled.
 *
 * The generic editor renders whatever the bridge sent, in the order it sent it
 * — which for this family is a row per item: a device picker, then three
 * unrelated numbers, then the next profile's picker. Correct, and unreadable.
 * Here the timing rows stay generic and each profile becomes a card.
 */
function ShabbatGroups({
  snapshot,
  request,
  writesEnabled,
}: {
  snapshot: ResourceSnapshot;
  request: (item: ManagedItem, value: unknown, operation?: string) => void;
  writesEnabled: boolean;
}) {
  const profiles = snapshot.groups.filter((group) => group.id !== 'timing');
  const timingItems = snapshot.groups
    .filter((group) => group.id === 'timing')
    .flatMap((group) => group.items);

  // A time that a profile card now carries is not repeated up here. Two
  // controls for one item is how the same value gets changed twice by someone
  // who thought they were looking at two settings.
  const claimed = new Set(
    profiles
      .flatMap((group) => [PROFILE_TIME[group.id], PROFILE_ENABLED[group.id]])
      .filter(Boolean),
  );
  const general = timingItems.filter((item) => !claimed.has(item.id));

  return (
    <div className="space-y-4">
      {general.length > 0 ? (
        <ResourceEditor
          snapshot={{
            ...snapshot,
            groups: [{ id: 'timing', label: 'זמנים', description: null, items: general }],
          }}
          onChange={request}
          writesEnabled={writesEnabled}
        />
      ) : null}

      <ul className="grid gap-3 lg:grid-cols-2">
        {profiles.map((group) => {
          const timeId = PROFILE_TIME[group.id];
          const timeItem = timeId
            ? timingItems.find((item) => item.id === timeId)
            : undefined;
          const enabledId = PROFILE_ENABLED[group.id];
          const enabledItem = enabledId
            ? timingItems.find((item) => item.id === enabledId)
            : undefined;
          return (
            <ProfileEditor
              key={group.id}
              label={group.label}
              description={
                RELATIVE_TO_CANDLES.has(group.id)
                  ? 'רץ לפני כניסת השבת, לפי ההכנה שנקבעה למעלה.'
                  : ADDED_CLOCK.has(group.id)
                    ? 'רץ בשעה שנקבעה כאן, כל עוד השבת או החג בתוקף.'
                    : undefined
              }
              items={group.items}
              writesEnabled={writesEnabled}
              onChange={request}
              timeControl={
                enabledItem || timeItem ? (
                  <div className="divide-y divide-slate-200 dark:divide-slate-700">
                    {enabledItem ? (
                      <ItemRow
                        item={enabledItem}
                        onChange={request}
                        writesEnabled={writesEnabled}
                      />
                    ) : null}
                    {timeItem ? (
                      <ItemRow item={timeItem} onChange={request} writesEnabled={writesEnabled} />
                    ) : null}
                  </div>
                ) : undefined
              }
            />
          );
        })}
      </ul>
    </div>
  );
}

export function ShabbatPage() {
  const query = useShabbat();
  const managed = useManagedFamily('shabbat');

  return (
    <>
      <PageHeader
        title="שעון שבת"
        description="זמני השבת והפרופילים שבובי מפעיל סביבם."
      />

      <QueryBoundary
        isLoading={query.isLoading}
        error={query.error}
        data={query.data}
        errorMessage="לא הצלחתי לקבל את הגדרות שעון השבת מ-Home Assistant"
        loadingLabel="טוען זמני שבת…"
        onRetry={() => void query.refetch()}
      >
        {(config) => (
          <div className="space-y-6">
            {/*
              The two numbers the week is planned around, given the room they
              deserve. They used to sit as small print beside the parasha, and
              they used to be timestamps: `2026-08-28T15:51:00+00:00`, which is
              neither the right hour here nor a thing anyone reads.
            */}
            <Card className="bg-gradient-to-bl from-bobi-50 to-white dark:from-bobi-500/10 dark:to-slate-800/60">
              <div className="flex items-center gap-2">
                <Flame
                  aria-hidden="true"
                  size={20}
                  className="shrink-0 text-bobi-600 dark:text-bobi-400"
                />
                <div className="min-w-0">
                  <p className="truncate text-base font-semibold text-slate-900 dark:text-slate-50">
                    {config.parasha ? parashaTitle(config.parasha) : 'השבת הקרובה'}
                  </p>
                  <p className="truncate text-xs text-slate-500 dark:text-slate-400">
                    {[config.hebrew_date, config.holiday].filter(Boolean).join(' · ')}
                  </p>
                </div>
              </div>

              <dl className="mt-4 grid grid-cols-2 gap-3">
                <ShabbatTime label="כניסת שבת" value={config.candle_lighting} />
                <ShabbatTime label="צאת שבת" value={config.havdalah} />
              </dl>

              {config.pre_shabbat_offset_minutes !== null ? (
                <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
                  בובי מכין את הבית {config.pre_shabbat_offset_minutes} דקות לפני הכניסה.
                </p>
              ) : null}
            </Card>

            {config.has_draft ? (
              <Card className="border-amber-200 bg-amber-50/60 dark:border-amber-500/30 dark:bg-amber-500/10">
                <p className="text-sm text-amber-900 dark:text-amber-200">
                  {config.draft_owners.length > 0
                    ? `קיימת טיוטה שמורה של ${config.draft_owners.join(', ')}.`
                    : 'קיימת טיוטה שנשמרה ב-Home Assistant.'}{' '}
                  היא נערכת ב-Home Assistant.
                </p>
              </Card>
            ) : null}

            {/*
              The profiles and the air-conditioner temperatures, read-only.

              Shown only while the management bridge is absent. When it is
              there, the section below renders the same three groups — timing,
              profiles, temperatures — with working controls, and printing both
              meant the screen said everything twice: once as a card you could
              not touch and again as a field you could, several thumb-lengths
              apart. Same values, twice the page, and the editable copy was the
              one you had to scroll to find.
            */}
            {managed.available ? null : (
              <>
                <section aria-labelledby="profiles-heading">
                  <SectionTitle>
                    <span id="profiles-heading">פרופילים</span>
                  </SectionTitle>
                  {config.profiles.length === 0 ? (
                    <EmptyState title="לא הוגדרו פרופילים לשבת" />
                  ) : (
                    <ul className="grid gap-3 lg:grid-cols-2">
                      {config.profiles.map((profile) => (
                        <ProfileCard key={profile.id} profile={profile} />
                      ))}
                    </ul>
                  )}
                </section>

                <section aria-labelledby="ac-heading">
                  <SectionTitle>
                    <span id="ac-heading">טמפרטורות מזגנים</span>
                  </SectionTitle>
                  {config.ac_temperatures.length === 0 ? (
                    <EmptyState title="לא הוגדרו טמפרטורות למזגנים" />
                  ) : (
                    <Card className="p-0">
                      <dl className="divide-y divide-slate-100 dark:divide-slate-700/60">
                        {config.ac_temperatures.map((entry) => (
                          <div
                            key={entry.id}
                            className="flex items-baseline justify-between gap-4 px-4 py-3"
                          >
                            <dt className="text-sm text-slate-700 dark:text-slate-200">
                              {entry.label}
                            </dt>
                            <dd className="text-sm font-medium tabular-nums text-slate-900 dark:text-slate-100">
                              {/* A setting the bridge does not express as a
                                  number — "auto", say — is shown as it came. */}
                              {entry.temperature !== null ? `${entry.temperature}°` : entry.text}
                            </dd>
                          </div>
                        ))}
                      </dl>
                    </Card>
                  )}
                </section>
              </>
            )}
          </div>
        )}
      </QueryBoundary>

      <div className="mt-6">
        <ManagedSection resource="shabbat" title="פרופילים וזמנים">
          {({ snapshot, request, writesEnabled }) => (
            <ShabbatGroups snapshot={snapshot} request={request} writesEnabled={writesEnabled} />
          )}
        </ManagedSection>
      </div>
    </>
  );
}
