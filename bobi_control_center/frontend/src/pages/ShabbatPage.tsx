import { Flame } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card, SectionTitle } from '@/components/ui/Card';
import { AdvancedDisclosure, TechnicalDetails } from '@/components/ui/Advanced';
import { PageHeader } from '@/components/ui/PageHeader';
import { DisabledAction, ReadOnlyNotice } from '@/components/ui/ReadOnly';
import { EmptyState, QueryBoundary } from '@/components/state/QueryBoundary';
import { useShabbat } from '@/hooks/queries';
import type { BridgeShabbat, ShabbatProfile } from '@/types/api';
import { displayValue } from '@/utils/format';

/** Resolve a device token to its friendly label — a raw token is never shown. */
function labelFor(config: BridgeShabbat, token: string): string {
  return config.device_labels?.[token] ?? token;
}

function ProfileCard({
  title,
  profile,
  config,
}: {
  title: string;
  profile: ShabbatProfile | null;
  config: BridgeShabbat;
}) {
  if (!profile) {
    return (
      <Card as="li">
        <h3 className="font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">לא מוגדר פרופיל.</p>
      </Card>
    );
  }

  return (
    <Card as="li" className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
          <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
            {profile.label ?? profile.name ?? '—'}
          </p>
        </div>
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
        {profile.offset_minutes !== null && profile.offset_minutes !== undefined ? (
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
            {profile.devices.map((token) => (
              <Badge key={token} tone="info">
                {labelFor(config, token)}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}

      <AdvancedDisclosure title="פרטים טכניים">
        <TechnicalDetails
          source={profile as unknown as Record<string, unknown>}
          known={[
            ['id', 'מזהה'],
            ['devices', 'טוקני מכשירים'],
          ]}
          hide={['name', 'label', 'active', 'time', 'offset_minutes']}
        />
      </AdvancedDisclosure>
    </Card>
  );
}

export function ShabbatPage() {
  const query = useShabbat();

  return (
    <>
      <PageHeader
        title="שעון שבת"
        description="זמני השבת והפרופילים שבובי מפעיל סביבם."
      />

      <ReadOnlyNotice className="mb-4">
        מסך שעון השבת מציג את ההגדרות הקיימות. שמירת שינויים תהיה זמינה בשלב הבא.
      </ReadOnlyNotice>

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
                      השבת הקרובה
                    </p>
                    {config.pre_shabbat_offset_minutes !== null &&
                    config.pre_shabbat_offset_minutes !== undefined ? (
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
                  קיימת טיוטה שנשמרה ב-Home Assistant. ניהול טיוטות מהממשק יהיה זמין בשלב הבא.
                </p>
              </Card>
            ) : null}

            <section aria-labelledby="profiles-heading">
              <SectionTitle
                action={<DisabledAction>עריכת פרופילים</DisabledAction>}
              >
                <span id="profiles-heading">פרופילים</span>
              </SectionTitle>
              <ul className="grid gap-3 lg:grid-cols-2">
                <ProfileCard
                  title="כיבוי לפני שבת"
                  profile={config.pre_off_profile}
                  config={config}
                />
                <ProfileCard
                  title="הדלקה לפני שבת"
                  profile={config.pre_on_profile}
                  config={config}
                />
                <ProfileCard
                  title="כיבוי לילה"
                  profile={config.night_off_profile}
                  config={config}
                />
                <ProfileCard
                  title="הדלקת בוקר"
                  profile={config.morning_on_profile}
                  config={config}
                />
              </ul>
            </section>

            <section aria-labelledby="ac-heading">
              <SectionTitle>
                <span id="ac-heading">טמפרטורות מזגנים</span>
              </SectionTitle>
              {Object.keys(config.ac_temperatures ?? {}).length === 0 ? (
                <EmptyState title="לא הוגדרו טמפרטורות למזגנים" />
              ) : (
                <Card className="p-0">
                  <dl className="divide-y divide-slate-100 dark:divide-slate-700/60">
                    {Object.entries(config.ac_temperatures).map(([token, value]) => (
                      <div
                        key={token}
                        className="flex items-baseline justify-between gap-4 px-4 py-3"
                      >
                        <dt className="text-sm text-slate-700 dark:text-slate-200">
                          {labelFor(config, token)}
                        </dt>
                        <dd className="text-sm font-medium tabular-nums text-slate-900 dark:text-slate-100">
                          {displayValue(value)}°
                        </dd>
                      </div>
                    ))}
                  </dl>
                </Card>
              )}
            </section>
          </div>
        )}
      </QueryBoundary>
    </>
  );
}
