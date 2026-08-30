/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        // Hebrew-first stack; Heebo/Rubik if the OS has them, else system UI.
        sans: [
          'Heebo',
          'Rubik',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Arial',
          'sans-serif',
        ],
      },
      colors: {
        // A calm indigo/slate identity — deliberately not Home Assistant blue.
        bobi: {
          50: '#eef2ff',
          100: '#e0e7ff',
          200: '#c7d2fe',
          300: '#a5b4fc',
          400: '#818cf8',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          800: '#3730a3',
          900: '#312e81',
        },
        // The ground the warm screens sit on.
        //
        // Slate is a cold grey with blue in it, and a whole page of it reads
        // like a control panel. This is the same lightness with the hue turned
        // the other way, so a card looks like paper on a table rather than a
        // window in an enclosure. Indigo above stays the identity — the warmth
        // is the surface it sits on, not a change of brand.
        warm: {
          50: '#faf8f5',
          100: '#f4f0ea',
          200: '#e9e2d8',
          300: '#d8ccbc',
          400: '#bda98f',
          500: '#a08a6d',
          600: '#856f54',
          700: '#6b5843',
          800: '#4a3d2f',
          900: '#2b241c',
        },
      },
      borderRadius: {
        xl: '1rem',
        '2xl': '1.25rem',
        '3xl': '1.75rem',
      },
      boxShadow: {
        card: '0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px -12px rgba(15, 23, 42, 0.12)',
        lift: '0 2px 4px rgba(15, 23, 42, 0.06), 0 16px 32px -16px rgba(15, 23, 42, 0.2)',
      },
      spacing: {
        // iPhone safe areas, applied by the app shell.
        'safe-top': 'env(safe-area-inset-top)',
        'safe-bottom': 'env(safe-area-inset-bottom)',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: { 'fade-in': 'fade-in 0.2s ease-out' },
    },
  },
  plugins: [],
};
