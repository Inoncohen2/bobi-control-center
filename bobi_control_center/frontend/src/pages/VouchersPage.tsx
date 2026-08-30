/**
 * ארנק השוברים.
 *
 * A voucher gets into this wallet by being photographed into WhatsApp: Bobi
 * reads the provider, the item, the brand, the expiry and the code off the
 * picture and stores them as fields, with a confidence. That is why this screen
 * has no "add" form and the family has no `create` verb — a web form would be a
 * second, worse source of truth for the same object, and a hand-typed expiry
 * date is exactly the field you do not want to be wrong.
 *
 * ## The code
 *
 * A voucher code is money. It is also the whole point of keeping the voucher,
 * so hiding it outright would make the wallet decorative.
 *
 * Bobi already draws this line: it redacts the code in the structured block it
 * stores while leaving it in the free text it extracted. This screen keeps the
 * same posture — the code is never on the card, and revealing one is a
 * deliberate press on that one voucher. A family screen that a guest can glance
 * at, or that gets photographed and sent to someone, should not have redeemable
 * codes sitting on it in plain sight.
 */

import { useState } from 'react';
import { Ticket } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Tile } from '@/components/ui/Tile';
import { ManagedResourcePage } from '@/features/manage/ManagedResourcePage';
import type { ManagedItem } from '@/types/api';

/** `14.10.2026` → a Date, or null. Bobi writes day-first; `Date` reads it US-first. */
function parseExpiry(value: unknown): Date | null {
  if (typeof value !== 'string') return null;
  const match = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(value.trim());
  if (!match) return null;
  const [, day, month, year] = match;
  const at = new Date(Number(year), Number(month) - 1, Number(day));
  return Number.isNaN(at.getTime()) ? null : at;
}

/** Whole days from today until the expiry; negative once it has passed. */
function daysLeft(expiry: Date): number {
  const midnight = new Date();
  midnight.setHours(0, 0, 0, 0);
  return Math.round((expiry.getTime() - midnight.getTime()) / 86_400_000);
}

function ExpiryBadge({ raw }: { raw: unknown }) {
  const expiry = parseExpiry(raw);
  if (expiry === null) {
    // Unparseable is not the same as absent, and neither is a reason to hide
    // what the bridge sent. Show it as it came.
    return typeof raw === 'string' && raw ? <Badge tone="neutral">בתוקף עד {raw}</Badge> : null;
  }

  const left = daysLeft(expiry);
  if (left < 0) return <Badge tone="neutral">פג בתוקף</Badge>;
  if (left === 0) return <Badge tone="warning">היום האחרון</Badge>;
  if (left <= 14) return <Badge tone="warning">עוד {left} ימים</Badge>;
  return <Badge tone="neutral">בתוקף עד {String(raw)}</Badge>;
}

function VoucherCard({ item }: { item: ManagedItem }) {
  const [revealed, setRevealed] = useState(false);
  const used = item.value === true;

  const provider = typeof item.detail.provider === 'string' ? item.detail.provider : null;
  const brand = typeof item.detail.brand === 'string' ? item.detail.brand : null;
  const code = typeof item.detail.code === 'string' ? item.detail.code : null;

  return (
    <li
      className={
        used
          ? 'rounded-2xl border border-warm-200/70 bg-warm-50 px-4 py-3.5 opacity-70 dark:border-warm-800/60 dark:bg-warm-900/30'
          : 'rounded-2xl border border-warm-200/70 bg-white px-4 py-3.5 dark:border-warm-800/60 dark:bg-warm-900/40'
      }
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p
            className={
              used
                ? 'truncate font-medium text-warm-500 line-through dark:text-warm-400'
                : 'truncate font-medium text-warm-900 dark:text-warm-50'
            }
          >
            {item.label}
          </p>
          {provider || brand ? (
            <p className="mt-0.5 truncate text-sm text-warm-600 dark:text-warm-300">
              {[provider, brand].filter(Boolean).join(' · ')}
            </p>
          ) : null}
        </div>
        {used ? <Badge tone="neutral">מומש</Badge> : <ExpiryBadge raw={item.detail.expiry_date} />}
      </div>

      {code && !used ? (
        <div className="mt-3">
          {revealed ? (
            <p className="select-all rounded-xl bg-warm-100 px-3 py-2 font-mono text-sm tracking-wider text-warm-900 dark:bg-warm-800 dark:text-warm-50">
              {code}
            </p>
          ) : (
            <Button variant="secondary" onClick={() => setRevealed(true)}>
              הצג קוד מימוש
            </Button>
          )}
        </div>
      ) : null}
    </li>
  );
}

export function VouchersPage() {
  return (
    <ManagedResourcePage
      resource="vouchers"
      title="ארנק השוברים"
      description="שוברים שצילמתם לבובי בוואטסאפ."
    >
      {({ snapshot }) => {
        const live = snapshot.items.filter((item) => item.value !== true);
        const used = snapshot.items.filter((item) => item.value === true);

        if (snapshot.items.length === 0) {
          return (
            <Card>
              <p className="text-sm text-warm-600 dark:text-warm-300">
                אין כרגע שוברים בארנק. שלחו לבובי תמונה של שובר בוואטסאפ והוא יישמר כאן.
              </p>
            </Card>
          );
        }

        return (
          <div className="space-y-4">
            <Tile title="בתוקף" icon={Ticket} tone="shopping" count={live.length}>
              {live.length === 0 ? (
                <p className="text-sm text-warm-500 dark:text-warm-400">
                  אין שוברים בתוקף כרגע.
                </p>
              ) : (
                <ul className="space-y-2.5">
                  {live.map((item) => (
                    <VoucherCard key={item.id} item={item} />
                  ))}
                </ul>
              )}
            </Tile>

            {used.length > 0 ? (
              <Tile title="מומשו" icon={Ticket} tone="neutral">
                <ul className="space-y-2.5">
                  {used.map((item) => (
                    <VoucherCard key={item.id} item={item} />
                  ))}
                </ul>
              </Tile>
            ) : null}
          </div>
        );
      }}
    </ManagedResourcePage>
  );
}
