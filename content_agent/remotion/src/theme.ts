import '@fontsource/inter/400.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/800.css';
import '@fontsource/jetbrains-mono/400.css';
import '@fontsource/jetbrains-mono/700.css';
import '@fontsource/playfair-display/700.css';
import '@fontsource/archivo-black/400.css';
import '@fontsource/montserrat/800.css';
import '@fontsource/montserrat/900.css';
import '@fontsource/bangers/400.css';
import '@fontsource/dm-serif-display/400.css';
import '@fontsource/orbitron/800.css';
import '@fontsource/pixelify-sans/400.css';
import '@fontsource/pixelify-sans/600.css';
import '@fontsource/pixelify-sans/700.css';
import '@fontsource/space-grotesk/500.css';
import '@fontsource/space-grotesk/700.css';
import '@fontsource/special-elite/400.css';
import '@fontsource/unbounded/700.css';
import '@fontsource/unbounded/800.css';
import '@fontsource/manrope/600.css';
import '@fontsource/manrope/800.css';
import '@fontsource/rubik/500.css';
import '@fontsource/rubik/700.css';
import '@fontsource/rubik/800.css';
import '@fontsource/caveat/700.css';
import '@fontsource/oswald/600.css';
import '@fontsource/oswald/700.css';
import './pixel-digits.css';
import {createContext, useContext} from 'react';

export type Palette = {
  bg1: string;
  bg2: string;
  text: string;
  muted: string;
  accent: string;
  accent2: string;
  land: string;
  landStroke: string;
  grid: string;
  panel: string;
};

export const PALETTES: Record<string, Palette> = {
  midnight: {
    bg1: '#0b1020', bg2: '#1a2442', text: '#f3efe4', muted: '#9aa4bb', accent: '#f2b84b', accent2: '#62b6cb',
    land: '#1f2a4d', landStroke: '#33467a', grid: 'rgba(255,255,255,0.05)', panel: 'rgba(255,255,255,0.06)',
  },
  parchment: {
    bg1: '#efe6d2', bg2: '#dccba6', text: '#2a2118', muted: '#6b5d4a', accent: '#a4452c', accent2: '#2f5d62',
    land: '#d6c39b', landStroke: '#b39a6b', grid: 'rgba(60,40,20,0.07)', panel: 'rgba(60,40,20,0.06)',
  },
  slate: {
    bg1: '#101317', bg2: '#202833', text: '#eef1f4', muted: '#8d98a6', accent: '#ff6b4a', accent2: '#4ac6ff',
    land: '#242c37', landStroke: '#3a4655', grid: 'rgba(255,255,255,0.05)', panel: 'rgba(255,255,255,0.06)',
  },
  // graphite with Claude-like clay orange accents: orange as the highlight, not the background
  clay: {
    bg1: '#141413', bg2: '#262624', text: '#faf9f5', muted: '#a8a59b', accent: '#d97757', accent2: '#e8b28f',
    land: '#2b2a27', landStroke: '#3d3b37', grid: 'rgba(255,255,255,0.05)', panel: 'rgba(255,255,255,0.06)',
  },
  // electric: deep navy, cyan and lime (connections, data flowing)
  volt: {
    bg1: '#050a18', bg2: '#0c1a3a', text: '#eaf6ff', muted: '#8ba3c7', accent: '#2ef2ff', accent2: '#c8ff3c',
    land: '#0f1f40', landStroke: '#1e3766', grid: 'rgba(46,242,255,0.06)', panel: 'rgba(255,255,255,0.06)',
  },
  // an old green-phosphor terminal
  crt: {
    bg1: '#08140c', bg2: '#13291b', text: '#d8ffdc', muted: '#6fa878', accent: '#39ff7a', accent2: '#ffcf3a',
    land: '#0d1f10', landStroke: '#1b3a20', grid: 'rgba(57,255,122,0.06)', panel: 'rgba(57,255,122,0.07)',
  },
  // light and playful: cream, violet and pink
  candy: {
    bg1: '#fff4e6', bg2: '#ffffff', text: '#1c1530', muted: '#6d6480', accent: '#7b3fe4', accent2: '#ff4f8b',
    land: '#f3e6d6', landStroke: '#e2cdb3', grid: 'rgba(28,21,48,0.05)', panel: 'rgba(28,21,48,0.05)',
  },
  // a ruled notebook page: ink blue and a yellow highlighter
  notebook: {
    bg1: '#fbf7ee', bg2: '#f3ecdc', text: '#1d2433', muted: '#6c7385', accent: '#2556e8', accent2: '#ffd43b',
    land: '#ece3cf', landStroke: '#d8cbb0', grid: 'rgba(37,86,232,0.08)', panel: 'rgba(29,36,51,0.05)',
  },
  // a security warning: near black, alarm red, warning yellow
  alert: {
    bg1: '#0b0a0c', bg2: '#1e0c10', text: '#fff4f4', muted: '#b39b9e', accent: '#ff2d4a', accent2: '#ffe14a',
    land: '#251015', landStroke: '#3d1a21', grid: 'rgba(255,45,74,0.06)', panel: 'rgba(255,255,255,0.06)',
  },
  // a warm sunset gradient: coral to violet, white type, a yellow key word
  sunset: {
    bg1: '#ff6b4a', bg2: '#6b3df0', text: '#ffffff', muted: '#ffe2d6', accent: '#ffe14d', accent2: '#ff3d7f',
    land: '#ff8a6a', landStroke: '#ffb39c', grid: 'rgba(255,255,255,0.08)', panel: '#2b1456', // deep violet windows: white text reads on them
  },
  // a newspaper page: off-white, black type, one red
  editorial: {
    bg1: '#f4f1ea', bg2: '#ffffff', text: '#141414', muted: '#6b6b6b', accent: '#e63312', accent2: '#141414',
    land: '#e8e3d8', landStroke: '#cfc8b8', grid: 'rgba(0,0,0,0.07)', panel: 'rgba(0,0,0,0.045)',
  },
  // bright orange: dark text, navy highlights; for Shorts that should not look like the dark ones
  ember: {
    bg1: '#ff6a13', bg2: '#ff9a3c', text: '#1b1206', muted: '#5e3412', accent: '#14213d', accent2: '#ffffff',
    land: '#ff8a2e', landStroke: '#e05a00', grid: 'rgba(0,0,0,0.06)', panel: 'rgba(0,0,0,0.10)',
  },
};

// The active style sets these CSS variables (styles.tsx), so every template follows the style's fonts.
export const FONTS = {
  serif: 'var(--font-display, "Playfair Display", Georgia, serif)',
  sans: 'var(--font-body, Inter, "Helvetica Neue", Arial, sans-serif)',
  caption: 'var(--font-caption, Inter, Arial, sans-serif)',
  impact: 'var(--font-impact, Inter, Arial, sans-serif)',
};

export const PaletteContext = createContext<Palette>(PALETTES.midnight);
export const usePalette = () => useContext(PaletteContext);
