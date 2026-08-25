import {
  Activity,
  AlertTriangle,
  Bell,
  Bot,
  CalendarCheck,
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

export const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'בית', icon: Home, primary: true },
  { to: '/capabilities', label: 'יכולות', icon: Sparkles },
  { to: '/devices', label: 'מכשירים', icon: Bot, primary: true },
  { to: '/automations', label: 'אוטומציות', icon: Timer, primary: true },
  { to: '/shabbat', label: 'שעון שבת', icon: Flame, primary: true },
  { to: '/notifications', label: 'הודעות חכמות', icon: Bell },
  { to: '/tasks', label: 'משימות ויומן', icon: CalendarCheck },
  { to: '/users', label: 'משתמשים', icon: Users },
  // "בדיקות" leads to the manual Test Center; the automated regression suites
  // live at /tests and are linked from there.
  { to: '/test-center', label: 'בדיקות', icon: Activity },
  { to: '/diagnostics', label: 'תקלות', icon: AlertTriangle },
  { to: '/settings', label: 'הגדרות', icon: Settings },
];

export const PRIMARY_NAV = NAV_ITEMS.filter((item) => item.primary);
export const SECONDARY_NAV = NAV_ITEMS.filter((item) => !item.primary);
