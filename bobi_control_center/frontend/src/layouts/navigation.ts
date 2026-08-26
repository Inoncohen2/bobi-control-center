import {
  Activity,
  AlertTriangle,
  Bell,
  Boxes,
  Calendar,
  CheckSquare,
  Cpu,
  Flame,
  Home,
  Settings,
  Sparkles,
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
 */
export const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'ראשי', icon: Home, primary: true },
  { to: '/tasks', label: 'משימות', icon: CheckSquare, primary: true },
  { to: '/devices', label: 'מכשירים', icon: Boxes, primary: true },
  { to: '/cameras', label: 'מצלמות', icon: Video },
  { to: '/shabbat', label: 'שעון שבת', icon: Flame, primary: true },
  { to: '/rules', label: 'אוטומציות', icon: Timer, primary: true },
  { to: '/calendar', label: 'יומן', icon: Calendar },
  { to: '/notifications', label: 'התראות חכמות', icon: Bell },
  { to: '/users', label: 'משתמשים', icon: Users },
  { to: '/settings', label: 'AI והגדרות', icon: Settings },
  { to: '/system', label: 'מערכת', icon: Cpu },
  { to: '/activity', label: 'פעילות', icon: Activity },
  { to: '/capabilities', label: 'יכולות', icon: Sparkles },
  { to: '/test-center', label: 'בדיקות', icon: Activity },
  { to: '/diagnostics', label: 'תקלות', icon: AlertTriangle },
];

export const PRIMARY_NAV = NAV_ITEMS.filter((item) => item.primary);
export const SECONDARY_NAV = NAV_ITEMS.filter((item) => !item.primary);
