/**
 * Maps the icon names the API returns onto Lucide components.
 *
 * The API sends a name rather than a component so the backend stays free of
 * frontend concerns; unknown names fall back to a neutral icon instead of
 * crashing the page.
 */

import {
  AirVent,
  AlertTriangle,
  Archive,
  Battery,
  Bell,
  Blinds,
  Bot,
  Calendar,
  CalendarClock,
  Camera,
  CameraOff,
  Car,
  Check,
  CheckSquare,
  Clock,
  Flame,
  Gauge,
  Home,
  Image,
  Lightbulb,
  MessageCircle,
  MessageCircleOff,
  Mic,
  Moon,
  Plug,
  Settings,
  Sparkles,
  Terminal,
  Thermometer,
  ToggleRight,
  Waves,
  type LucideIcon,
} from 'lucide-react';

const ICONS: Record<string, LucideIcon> = {
  'air-vent': AirVent,
  'alert-triangle': AlertTriangle,
  archive: Archive,
  'battery-low': Battery,
  bell: Bell,
  blinds: Blinds,
  bot: Bot,
  calendar: Calendar,
  'calendar-clock': CalendarClock,
  camera: Camera,
  'camera-off': CameraOff,
  candlestick: Flame,
  car: Car,
  check: Check,
  'check-square': CheckSquare,
  clock: Clock,
  gauge: Gauge,
  house: Home,
  home: Home,
  image: Image,
  lightbulb: Lightbulb,
  'message-circle': MessageCircle,
  'message-circle-off': MessageCircleOff,
  mic: Mic,
  moon: Moon,
  plug: Plug,
  settings: Settings,
  sparkles: Sparkles,
  terminal: Terminal,
  thermometer: Thermometer,
  'toggle-right': ToggleRight,
  water: Waves,
};

export function iconFor(name: string | undefined | null): LucideIcon {
  return (name ? ICONS[name] : undefined) ?? Plug;
}
