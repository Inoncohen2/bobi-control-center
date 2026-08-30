import {
  Activity,
  AlertTriangle,
  Bell,
  Boxes,
  Calendar,
  CheckSquare,
  Clapperboard,
  Cable,
  Cpu,
  Flame,
  Home,
  ShoppingCart,
  Ticket,
  Settings,
  SlidersHorizontal,
  Sparkles,
  ScrollText,
  Workflow,
  Timer,
  Users,
  Video,
  type LucideIcon,
} from 'lucide-react';

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Shown in the mobile bottom bar rather than behind "עוד". */
  primary?: boolean;
}

/**
 * Every destination maps to a `bobi_cc_*` bridge service.
 *
 * The five marked `primary` are the ones a phone shows along the bottom, so
 * they are the five a household reaches for daily rather than the five that
 * happen to come first alphabetically. Everything else lives behind "עוד",
 * which is a full menu rather than an overflow.
 *
 * Five, and the bar is built from `PRIMARY_NAV.length + 1`, so a sixth would
 * fit rather than break — into about fifty points of width per tab on a phone,
 * which is under the size a thumb can reliably hit. Adding one therefore means
 * removing one, and `רשימות` displaced `אוטומציות`: shopping is opened daily,
 * and this house currently has no smart rules at all. Automations keep their
 * screen and their place in "עוד"; they stop holding a thumb-sized target for
 * a list that is empty.
 */
export const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'ראשי', icon: Home, primary: true },
  { to: '/tasks', label: 'משימות', icon: CheckSquare, primary: true },
  { to: '/lists', label: 'רשימות', icon: ShoppingCart, primary: true },
  { to: '/devices', label: 'מכשירים', icon: Boxes, primary: true },
  { to: '/vouchers', label: 'שוברים', icon: Ticket },
  { to: '/cameras', label: 'מצלמות', icon: Video },
  { to: '/shabbat', label: 'שעון שבת', icon: Flame, primary: true },
  { to: '/rules', label: 'אוטומציות', icon: Timer },
  { to: '/calendar', label: 'יומן', icon: Calendar },
  { to: '/helpers', label: 'עזרים', icon: SlidersHorizontal },
  { to: '/ha-automations', label: 'אוטומציות HA', icon: Workflow },
  { to: '/scripts', label: 'סקריפטים', icon: ScrollText },
  { to: '/scenes', label: 'סצנות', icon: Clapperboard },
  { to: '/notifications', label: 'התראות חכמות', icon: Bell },
  { to: '/users', label: 'משתמשים', icon: Users },
  { to: '/settings', label: 'AI והגדרות', icon: Settings },
  { to: '/system', label: 'מערכת', icon: Cpu },
  { to: '/activity', label: 'פעילות', icon: Activity },
  { to: '/capabilities', label: 'יכולות', icon: Sparkles },
  { to: '/test-center', label: 'בדיקות', icon: Activity },
  { to: '/diagnostics', label: 'תקלות', icon: AlertTriangle },
  { to: '/bridge-contract', label: 'חוזה הגשרים', icon: Cable },
];

export const PRIMARY_NAV = NAV_ITEMS.filter((item) => item.primary);
export const SECONDARY_NAV = NAV_ITEMS.filter((item) => !item.primary);
