import {geoGraticule10, geoInterpolate, geoNaturalEarth1, geoPath} from 'd3-geo';
import React, {useMemo} from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {feature, mesh} from 'topojson-client';
// Natural Earth 1:110m (public domain), shipped in the world-atlas npm package: works offline.
import countries110 from 'world-atlas/countries-110m.json';
import {firstCue, progress, rise} from '../anim';
import {FONTS, usePalette} from '../theme';
import type {SceneProps} from '../types';

const topo = countries110 as any;
const LAND = feature(topo, topo.objects.land) as any;
const BORDERS = mesh(topo, topo.objects.countries, (a: any, b: any) => a !== b) as any;
const GRATICULE = geoGraticule10();

type Place = {name: string; lat: number; lon: number};

const PLANE =
  'M 0 -22 C 3 -22 4 -16 4 -10 L 4 -4 L 22 6 L 22 10 L 4 4 L 3 16 L 9 21 L 9 24 L 0 21 L -9 24 L -9 21 L -3 16 L -4 4 L -22 10 L -22 6 L -4 -4 L -4 -10 C -4 -16 -3 -22 0 -22 Z';
const SHIP = 'M -18 4 L 18 4 L 13 14 L -13 14 Z M -2 -18 L 2 -18 L 2 4 L -2 4 Z M 2 -16 L 14 0 L 2 0 Z';

const Marker: React.FC<{x: number; y: number; label: string; color: string; t: number; u: number; above?: boolean}> = ({
  x, y, label, color, t, u, above,
}) => {
  const p = usePalette();
  const pulse = (t % 45) / 45;
  return (
    <g>
      <circle cx={x} cy={y} r={(10 + 26 * pulse) * u} fill="none" stroke={color} strokeWidth={2.5 * u} opacity={1 - pulse} />
      <circle cx={x} cy={y} r={10 * u} fill={color} stroke={p.bg1} strokeWidth={3 * u} />
      <text
        x={x}
        y={above ? y - 28 * u : y + 50 * u}
        textAnchor="middle"
        style={{fontFamily: FONTS.sans, fontWeight: 800, fontSize: 34 * u, fill: p.text, paintOrder: 'stroke', stroke: p.bg1, strokeWidth: 8 * u}}
      >
        {label}
      </text>
    </g>
  );
};

const MapBase: React.FC<{path: ReturnType<typeof geoPath>; u: number}> = ({path, u}) => {
  const p = usePalette();
  return (
    <g>
      <path d={path(GRATICULE) || ''} fill="none" stroke={p.grid} strokeWidth={1.2 * u} />
      <path d={path(LAND) || ''} fill={p.land} stroke={p.landStroke} strokeWidth={1.4 * u} />
      <path d={path(BORDERS) || ''} fill="none" stroke={p.landStroke} strokeWidth={0.8 * u} opacity={0.7} />
    </g>
  );
};

const Title: React.FC<{text?: string; u: number; start: number}> = ({text, u, start}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = usePalette();
  if (!text) return null;
  return (
    <div
      style={{
        position: 'absolute', top: 70 * u, left: 90 * u, display: 'flex', alignItems: 'stretch',
        background: 'rgba(0,0,0,0.45)', borderRadius: 12 * u, overflow: 'hidden', opacity: rise(frame, fps, start),
      }}
    >
      <div style={{width: 8 * u, background: p.accent}} />
      <div style={{padding: `${14 * u}px ${26 * u}px`, fontFamily: FONTS.sans, fontWeight: 800, fontSize: 40 * u, color: p.text}}>
        {text}
      </div>
    </div>
  );
};

export const MapRoute: React.FC<SceneProps> = ({props, speech: speechStart, duration, cues}) => {
  const frame = useCurrentFrame();
  const speech = firstCue(speechStart, cues); // the animation starts on the first cue; the title does not wait
  const {width, height} = useVideoConfig();
  const p = usePalette();
  const u = Math.min(width, height) / 1080;
  const a: Place = props.from;
  const b: Place = props.to;
  const {path, proj, pts} = useMemo(() => {
    const interp = geoInterpolate([a.lon, a.lat], [b.lon, b.lat]);
    const pts = Array.from({length: 120}, (_, i) => interp(i / 119));
    // Frame the route with generous context around it.
    const lons = pts.map((q) => q[0]);
    const lats = pts.map((q) => q[1]);
    const padLon = Math.max(14, (Math.max(...lons) - Math.min(...lons)) * 0.35);
    const padLat = Math.max(10, (Math.max(...lats) - Math.min(...lats)) * 0.6);
    const box = {
      type: 'MultiPoint',
      coordinates: [
        [Math.max(Math.min(...lons) - padLon, -180), Math.max(Math.min(...lats) - padLat, -85)],
        [Math.min(Math.max(...lons) + padLon, 180), Math.min(Math.max(...lats) + padLat, 85)],
      ],
    } as any;
    const proj = geoNaturalEarth1().fitExtent([[120 * u, 160 * u], [width - 120 * u, height - 140 * u]], box);
    return {path: geoPath(proj), proj, pts};
  }, [a.lat, a.lon, b.lat, b.lon, width, height, u]);

  const xy = pts.map((q) => proj(q as [number, number]) as [number, number]);
  const k = progress(frame, speech + 8, Math.min(duration - 12, speech + 8 + Math.max(60, (duration - speech) * 0.65)));
  const shown = Math.max(2, Math.round(k * (xy.length - 1)) + 1);
  const d = xy.slice(0, shown).map((q, i) => `${i ? 'L' : 'M'} ${q[0].toFixed(1)} ${q[1].toFixed(1)}`).join(' ');
  const head = xy[shown - 1];
  const prev = xy[Math.max(shown - 2, 0)];
  const angle = (Math.atan2(head[1] - prev[1], head[0] - prev[0]) * 180) / Math.PI + 90;
  const [ax, ay] = proj([a.lon, a.lat]) as [number, number];
  const [bx, by] = proj([b.lon, b.lat]) as [number, number];
  const zoom = interpolate(frame, [0, duration], [1, 1.06]);
  const vehicle = props.vehicle ?? 'plane';
  return (
    <AbsoluteFill>
      <svg width={width} height={height} style={{transform: `scale(${zoom})`, transformOrigin: `${(ax + bx) / 2}px ${(ay + by) / 2}px`}}>
        <MapBase path={path} u={u} />
        <path d={d} fill="none" stroke={p.accent} strokeWidth={5 * u} strokeLinecap="round" strokeDasharray={`${14 * u} ${10 * u}`} />
        <Marker x={ax} y={ay} label={a.name} color={p.accent2} t={frame} u={u} above={ay > by} />
        <g opacity={k > 0.97 ? 1 : 0.35}>
          <Marker x={bx} y={by} label={b.name} color={p.accent} t={frame} u={u} above={by >= ay} />
        </g>
        {vehicle !== 'none' && k > 0 && k < 1 && (
          <path d={vehicle === 'ship' ? SHIP : PLANE} transform={`translate(${head[0]} ${head[1]}) rotate(${vehicle === 'ship' ? 0 : angle}) scale(${1.6 * u})`} fill={p.text} stroke={p.bg1} strokeWidth={1.5} />
        )}
      </svg>
      <Title text={props.label} u={u} start={speechStart - 6} />
    </AbsoluteFill>
  );
};

export const MapPoint: React.FC<SceneProps> = ({props, speech: speechStart, duration, cues}) => {
  const frame = useCurrentFrame();
  const speech = firstCue(speechStart, cues); // the animation starts on the first cue; the title does not wait
  const {width, height} = useVideoConfig();
  const p = usePalette();
  const u = Math.min(width, height) / 1080;
  const place: Place = props.place;
  const zoom = Number(props.zoom || 4);
  const base = useMemo(() => geoNaturalEarth1().fitExtent([[60 * u, 80 * u], [width - 60 * u, height - 80 * u]], {type: 'Sphere'} as any), [width, height, u]);
  const k = progress(frame, Math.max(speech - 10, 0), Math.min(duration - 10, speech + 70));
  const scale = base.scale() * Math.pow(zoom, k);
  const proj = geoNaturalEarth1()
    .scale(scale)
    .center([place.lon * k, place.lat * k])
    .translate([width / 2, height / 2]);
  const path = geoPath(proj);
  const [x, y] = proj([place.lon, place.lat]) as [number, number];
  return (
    <AbsoluteFill>
      <svg width={width} height={height}>
        <MapBase path={path} u={u} />
        <g opacity={progress(frame, speech + 20, speech + 35)}>
          <Marker x={x} y={y} label={place.name} color={p.accent} t={frame} u={u} />
        </g>
      </svg>
      <Title text={props.label} u={u} start={speechStart - 6} />
    </AbsoluteFill>
  );
};
