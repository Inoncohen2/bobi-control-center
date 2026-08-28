import { Flame } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card, SectionTitle } from '@/components/ui/Card';
import { AdvancedDisclosure, TechnicalDetails } from '@/components/ui/Advanced';
import { PageHeader } from '@/components/ui/PageHeader';
import { EmptyState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useShabbat } from '@/hooks/queries';
import type { ShabbatProfile } from '@/types/api';
import { ManagedSection } from '@/features/manage/ManagedSection';
import { useManagedFamily } from '@/features/manage/useManagedFamily';
import { ResourceEditor } from '@/features/manage/ResourceEditor';

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
                  ניהול טיוטות מהממשק יהיה זמין בשלב הבא.
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
            <ResourceEditor snapshot={snapshot} onChange={request} writesEnabled={writesEnabled} />
          )}
        </ManagedSection>
      </div>
    </>
  );
}
