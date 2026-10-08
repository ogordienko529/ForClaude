import '@fontsource/inter/400.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/800.css';
import '@fontsource/playfair-display/700.css';
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
};

export const FONTS = {
  serif: '"Playfair Display", Georgia, serif',
  sans: 'Inter, "Helvetica Neue", Arial, sans-serif',
};

export const PaletteContext = createContext<Palette>(PALETTES.midnight);
export const usePalette = () => useContext(PaletteContext);
