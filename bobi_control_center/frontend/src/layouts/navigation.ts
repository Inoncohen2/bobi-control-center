import {
  Activity,
  AlertTriangle,
  Boxes,
  CheckSquare,
  Flame,
  Home,
  Settings,
  Sparkles,
  Timer,
  Users,
  type LucideIcon,
} from 'lucide-react';

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Shown in the mobile bottom bar rather than behind "עוד". */
  primary?: boolean;
}

/** Every destination maps to a `bobi_cc_*` bridge service. */
export const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'בית', icon: Home, primary: true },
  { to: '/devices', label: 'מכשירים', icon: Boxes, primary: true },
  { to: '/capabilities', label: 'יכולות', icon: Sparkles },
  { to: '/rules', label: 'כללים חכמים', icon: Timer, primary: true },
  { to: '/shabbat', label: 'שעון שבת', icon: Flame, primary: true },
  { to: '/tasks', label: 'משימות', icon: CheckSquare },
  { to: '/users', label: 'משתמשים', icon: Users },
  { to: '/test-center', label: 'בדיקות', icon: Activity },
  { to: '/diagnostics', label: 'תקלות', icon: AlertTriangle },
  { to: '/settings', label: 'הגדרות', icon: Settings },
];

export const PRIMARY_NAV = NAV_ITEMS.filter((item) => item.primary);
export const SECONDARY_NAV = NAV_ITEMS.filter((item) => !item.primary);
