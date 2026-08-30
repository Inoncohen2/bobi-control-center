/**
 * The household's own lists — shopping, recipes, reminders, the family list.
 *
 * Separate from the tasks screen on purpose. `tasks` is one list, addressed per
 * household member, and it has its own bridge. These are the *other* lists a
 * family keeps, and each one arrives as a group with its entries inside it.
 *
 * Which lists appear is the bridge's decision and this screen does not argue
 * with it. That is not deference for its own sake: the house has eighteen
 * `todo` lists and only about half belong to people. The rest are Bobi's own
 * machinery — an activity log of several hundred entries, a multimodal context
 * store keyed by chat id, a WhatsApp outbox — and a screen that rendered "every
 * list" would put a conversation log carrying phone numbers in front of the
 * family. So the allowlist lives in the bridge, where the household controls
 * it, and this screen renders exactly what it is handed.
 */

import { CheckCircle2, CookingPot, ShoppingCart, Users, type LucideIcon } from 'lucide-react';

import { Card } from '@/components/ui/Card';
import { Tile, type TileTone } from '@/components/ui/Tile';
import { ManagedResourcePage } from '@/features/manage/ManagedResourcePage';
import type { ManagedItem } from '@/types/api';

/**
 * How a list is dressed, by the id the bridge gives it.
 *
 * Keyed on the bridge's own group id rather than on the Hebrew label, because
 * a household that renames "קניות" to "סופר" should not lose its colour. A
 * list this table has never heard of still renders — in the neutral tone, with
 * a tick icon — rather than being dropped for being unfamiliar.
 */
const LIST_STYLES: Record<string, { tone: TileTone; icon: LucideIcon }> = {
  shopping: { tone: 'shopping', icon: ShoppingCart },
  recipes: { tone: 'recipes', icon: CookingPot },
  reminders: { tone: 'reminders', icon: CheckCircle2 },
  family: { tone: 'family', icon: Users },
};

/** What an empty list should say — never a bare "0". */
const EMPTY_TEXT: Record<string, string> = {
  shopping: 'אין מה לקנות כרגע.',
  recipes: 'עוד לא נשמרו מתכונים.',
  reminders: 'אין תזכורות פתוחות.',
  family: 'הרשימה ריקה.',
};

function ListEntry({ item }: { item: ManagedItem }) {
  const done = item.value === true;
  const due = typeof item.detail.due === 'string' ? item.detail.due : null;

  return (
    <li className="flex items-start gap-3 py-2.5">
      <span
        aria-hidden
        className={
          done
            ? 'mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-emerald-500 text-white'
            : 'mt-0.5 h-5 w-5 shrink-0 rounded-full border-2 border-warm-300 dark:border-warm-600'
        }
      >
        {done ? <CheckCircle2 className="h-3.5 w-3.5" /> : null}
      </span>
      <div className="min-w-0 flex-1">
        <p
          className={
            done
              ? 'truncate text-warm-500 line-through dark:text-warm-400'
              : 'truncate text-warm-900 dark:text-warm-50'
          }
        >
          {item.label}
        </p>
        {due ? (
          <p className="mt-0.5 text-xs text-warm-500 dark:text-warm-400">עד {due}</p>
        ) : null}
      </div>
      {/* The state in words as well as in the mark: a tick alone is a colour,
          and a colour alone is not readable to everyone. */}
      <span className="sr-only">{done ? 'בוצע' : 'פתוח'}</span>
    </li>
  );
}

export function ListsPage() {
  return (
    <ManagedResourcePage
      resource="lists"
      title="רשימות הבית"
      description="קניות, מתכונים, תזכורות — מה שהמשפחה שומרת."
    >
      {({ snapshot }) => {
        const groups = snapshot.groups.length > 0 ? snapshot.groups : [];

        if (groups.length === 0) {
          return (
            <Card>
              <p className="text-sm text-warm-600 dark:text-warm-300">
                הגשר לא פרסם אף רשימה.
              </p>
            </Card>
          );
        }

        return (
          <div className="grid gap-4 sm:grid-cols-2">
            {groups.map((group) => {
              const style = LIST_STYLES[group.id] ?? { tone: 'neutral' as TileTone, icon: CheckCircle2 };
              const open = group.items.filter((item) => item.value !== true);

              return (
                <Tile
                  key={group.id}
                  title={group.label ?? group.id}
                  icon={style.icon}
                  tone={style.tone}
                  count={open.length}
                >
                  {group.items.length === 0 ? (
                    <p className="text-sm text-warm-500 dark:text-warm-400">
                      {EMPTY_TEXT[group.id] ?? 'הרשימה ריקה.'}
                    </p>
                  ) : (
                    <ul className="divide-y divide-warm-100 dark:divide-warm-800/60">
                      {group.items.map((item) => (
                        <ListEntry key={item.id} item={item} />
                      ))}
                    </ul>
                  )}
                </Tile>
              );
            })}
          </div>
        );
      }}
    </ManagedResourcePage>
  );
}
