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
            <Card className="bg-gradient-to-bl from-bobi-50 to-white dark:from-bobi-500/10 dark:to-slate-800/60">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <Flame
                    aria-hidden="true"
                    size={22}
                    className="text-bobi-600 dark:text-bobi-400"
                  />
                  <div>
                    <p className="text-sm font-medium text-bobi-700 dark:text-bobi-300">
                      {config.parasha ?? 'השבת הקרובה'}
                    </p>
                    {config.pre_shabbat_offset_minutes !== null ? (
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        הכנה {config.pre_shabbat_offset_minutes} דקות לפני הכניסה
                      </p>
                    ) : null}
                  </div>
                </div>
                <dl className="flex gap-6">
                  <div>
                    <dt className="text-xs text-slate-500 dark:text-slate-400">כניסת שבת</dt>
                    <dd className="text-xl font-bold tabular-nums text-slate-900 dark:text-slate-50">
                      {config.candle_lighting ?? '—'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-slate-500 dark:text-slate-400">צאת שבת</dt>
                    <dd className="text-xl font-bold tabular-nums text-slate-900 dark:text-slate-50">
                      {config.havdalah ?? '—'}
                    </dd>
                  </div>
                </dl>
              </div>
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
