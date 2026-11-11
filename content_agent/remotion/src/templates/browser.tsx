/**
 * A generic browser window (tab strip, back/forward/reload, an address bar): the URL types in, the page
 * loads (a progress line and a skeleton), then either a page with a title and text lines (line i on
 * cue i) or a "not found" page with a big 404 and a shake. An optional mouse pointer clicks the
 * address bar and then follows the text.
 */
import React, {useMemo} from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {progress, rise} from '../anim';
import {PREROLL, Sfx, shake, slam, uiZone} from '../motion';
import {Pointer, Ripple, textWidth, WindowDots, wrapStarts} from '../screen';
import {useStyle} from '../styles';
import {usePalette} from '../theme';
import type {SceneProps} from '../types';
import {alpha, chatFamily, clamp, colours, contrast, mix, onColor, skin, useChatFonts} from './chat';

/** Darken a colour until it reads on a white page. */
const onWhite = (col: string, min = 4.5) => {
  let c = col;
  for (let i = 0; i < 6 && contrast(c, '#ffffff') < min; i++) c = mix(c, '#000000', 0.22);
  return c;
};

// ------------------------------------------------------------------ timing
export const browserTiming = (duration: number, speech: number, cues: (number | null)[], chars: number, n: number,
  notFound: boolean, cursor: boolean) => {
  const d = Math.max(duration, 36);
  const end = d * 0.8;
  const cueAt = (i: number) => (typeof cues[i] === 'number' ? clamp((cues[i] as number) - 4, 0, d * 0.9) : null);
  let typeStart = cursor ? clamp(speech - 6, 12, d * 0.1) : clamp(speech - 6, 3, d * 0.1);
  let typing = clamp(chars / 1.5, 8, d * 0.22);
  let loadLen = clamp(d * 0.11, 12, 24);
  // the 404 lands on cue 0 when there is one (a page's line 0 appears on it)
  const c0 = cueAt(0);
  let loaded = typeStart + typing + 4 + loadLen;
  if (c0 !== null && c0 < loaded) {
    const room = c0 - typeStart - 4;
    typing = Math.max(room * 0.6, 4);
    loadLen = Math.max(room - typing, 6);
    if (room < 12) typeStart = Math.max(0, c0 - 16);
    loaded = Math.max(c0, typeStart + typing + 4 + loadLen);
  } else if (c0 !== null && notFound) {
    // a late cue: load a little longer, and type the address later rather than show a long skeleton
    const late = c0 - loaded;
    loadLen += Math.min(late, 12);
    typeStart += Math.max(late - 12, 0);
    loaded = c0;
  }
  const click = cursor ? Math.max(typeStart - 4, 2) : null;
  const typeEnd = typeStart + typing;
  const enter = typeEnd + 4;
  const reveals: number[] = [];
  const first = notFound ? loaded + 12 : loaded + 6;
  for (let i = 0; i < n; i++) {
    const c = notFound ? null : cueAt(i);
    const prev = i ? reveals[i - 1] : first;
    if (c !== null) reveals.push(Math.max(c, i ? prev + 3 : loaded + 4));
    else if (i === 0) reveals.push(first);
    else {
      let j = i + 1;
      while (j < n && cueAt(j) === null) j++;
      const target = !notFound && j < n ? (cueAt(j) as number) : Math.max(end, prev + 3 * (n - i));
      const steps = !notFound && j < n ? j - i + 1 : n - i;
      reveals.push(Math.max(prev + (target - prev) / steps, prev + 3));
    }
  }
  return {appear: -PREROLL, click, typeStart, typeEnd, enter, loaded, reveals};
};

// ------------------------------------------------------------------ icons
const Icon: React.FC<{d: string; size: number; color: string}> = ({d, size, color}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" style={{flexShrink: 0}}>
    <path d={d} stroke={color} strokeWidth={2.4} fill="none" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const BACK = 'M15 5 L8 12 L15 19';
const FWD = 'M9 5 L16 12 L9 19';
const RELOAD = 'M19 12 A7 7 0 1 1 16.5 6.6 M17 3.5 L17 7.5 L13 7.5';
const LOCK = 'M7 11 L17 11 L17 20 L7 20 Z M9 11 L9 8 A3 3 0 0 1 15 8 L15 11';

// ------------------------------------------------------------------ the scene
export const Browser: React.FC<SceneProps> = ({props, duration, speech, cues}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const p = usePalette();
  const st = useStyle();
  const u = Math.min(width, height) / 1080;
  const vertical = height > width;

  const url = String(props.url ?? '');
  const notFound = props.state === 'notfound';
  const cursor = props.cursor === true;
  const lines: string[] = (Array.isArray(props.lines) ? props.lines : []).map((x: unknown) => String(x));
  const cyr = /[Ѐ-ӿ]/.test([props.title ?? '', ...lines].join(' '));
  const title = props.title ? String(props.title) : notFound ? (cyr ? 'Сторінку не знайдено' : 'Page not found') : '';
  const homeLabel = cyr ? 'На головну' : 'Go home';
  const domain = url.replace(/^[a-z]+:\/\//i, '').replace(/^www\./i, '').split(/[/?#]/)[0] || url;
  const all = [url, title, ...lines, homeLabel, '404'].join(' ');
  const family = chatFamily(st.fonts.body, all);
  const ready = useChatFonts(family, all);

  const c = colours(p);
  const sk = skin(st, p, c.dark, u);
  const strip = mix(c.win, c.dark ? '#000000' : p.text, c.dark ? 0.3 : 0.07);
  const field = mix(c.win, p.text, c.dark ? 0.09 : 0.06);
  const ink = onColor(c.win, [p.text]);
  const page = '#fcfcfa';
  const pageInk = '#1b1d22';
  const pageMuted = '#5f6670';
  const accentInk = onWhite(p.accent);
  const accent2Ink = onWhite(p.accent2, 3);
  const red = '#e5484d';

  // ---- geometry
  const zone = uiZone(width, height);
  const zoneH = zone.bottom - zone.top;
  const winW = vertical ? width - 120 * u : width * 0.62;
  const winH = vertical ? zoneH * 0.96 : zoneH * 0.94;
  const winLeft = (width - winW) / 2;
  const winTop = zone.top + (zoneH - winH) / 2;
  const tabH = 58 * u;
  const barH = 84 * u;
  const pageTop = tabH + barH;
  const pageH = winH - pageTop;
  const padP = 40 * u;
  const pageW = winW - 2 * padP;
  const urlFs = 29 * u;
  const fieldLeft = 24 * u + 3 * (40 * u + 10 * u);
  const fieldW = winW - fieldLeft - 70 * u;
  const urlTextW = fieldW - 2 * 20 * u - 34 * u;

  // the page's text sizes: the largest that fit
  const fit = useMemo(() => {
    for (let k = 1; k > 0.6; k -= 0.04) {
      const tFs = 58 * u * k;
      const lFs = 40 * u * k;
      const tH = title ? wrapStarts(title, 800, tFs, family, pageW).length * tFs * 1.15 : 0;
      const lH = lines.reduce((s, l) => s + wrapStarts(l, 400, lFs, family, pageW).length * lFs * 1.45 + 18 * u * k, 0);
      const header = 76 * u;
      const rest = header + 34 * u + tH + 26 * u + lH + padP;
      const hero = notFound ? 0 : Math.min(230 * u, pageH - rest - 20 * u);
      if (notFound || rest + Math.max(hero, 0) <= pageH) return {k, tFs, lFs, hero: hero >= 120 * u ? hero : 0};
    }
    return {k: 0.6, tFs: 58 * u * 0.6, lFs: 40 * u * 0.6, hero: 0};
  }, [ready, title, lines.join('\n'), family, pageW, pageH, notFound]);

  const t = browserTiming(duration, speech, cues, Array.from(url).length, lines.length, notFound, cursor);
  const appear = rise(frame, fps, t.appear, 16);
  const typedK = clamp((frame - t.typeStart) / Math.max(t.typeEnd - t.typeStart, 1), 0, 1);
  const typed = Array.from(url).slice(0, Math.round(Array.from(url).length * typedK)).join('');
  const typing = frame >= t.typeStart && frame < t.typeEnd;
  const focused = frame >= (t.click ?? t.typeStart - 6) && frame < t.enter + 2;
  const loading = frame >= t.enter && frame < t.loaded + 4;
  const loadK = progress(frame, t.enter, t.loaded);
  const isLoaded = frame >= t.loaded;
  const shift = Math.max(textWidth(typed, 600, urlFs, family) - urlTextW, 0);
  const jolt = notFound ? shake(frame, t.loaded, 30 * u, 22) : 0;
  const bad = notFound && isLoaded;

  // ---- the pointer: in from the lower right, clicks the address bar, then follows the text
  const fieldX = winLeft + fieldLeft + 60 * u + Math.min(textWidth(url, 600, urlFs, family), urlTextW) * 0.45;
  const fieldY = winTop + tabH + barH / 2;
  const contentX = (i: number) => winLeft + padP + Math.min(textWidth(lines[i] ?? '', 400, fit.lFs, family), pageW) * 0.92;
  let px = winLeft + winW * 0.86;
  let py = winTop + winH * 0.9;
  let press = 0;
  if (cursor && t.click !== null) {
    const toField = progress(frame, t.click - 14, t.click);
    px = interpolate(toField, [0, 1], [winLeft + winW * 0.86, fieldX]);
    py = interpolate(toField, [0, 1], [winTop + winH * 0.9, fieldY]);
    press = Math.max(0, 1 - Math.abs(frame - t.click) / 4);
    // aside while typing, so the URL stays readable
    const aside = progress(frame, t.typeStart, t.typeStart + 10);
    py += aside * 70 * u;
    px += aside * 40 * u;
  }

  // ---- page layout (positions inside the page area)
  const headerH = 76 * u;
  const heroTop = headerH + 24 * u;
  const titleTop = heroTop + (fit.hero ? fit.hero + 30 * u : 10 * u);
  const titleLines = title ? wrapStarts(title, 800, fit.tFs, family, pageW).length : 0;
  const linesTop = titleTop + titleLines * fit.tFs * 1.15 + 26 * u;
  const lineTops = lines.reduce<number[]>((acc, l, i) => {
    const prev = i ? acc[i - 1] + wrapStarts(lines[i - 1], 400, fit.lFs, family, pageW).length * fit.lFs * 1.45 + 18 * u * fit.k : linesTop;
    acc.push(prev);
    return acc;
  }, []);
  if (cursor && isLoaded && !notFound && lines.length) {
    // glide to the line being revealed
    let li = 0;
    t.reveals.forEach((r, i) => {
      if (frame >= r) li = i;
    });
    const k = progress(frame, t.reveals[li], t.reveals[li] + 10);
    const from = li ? li - 1 : -1;
    const fx = from < 0 ? px : contentX(from) + 20 * u;
    const fy = from < 0 ? py : winTop + pageTop + lineTops[from] + fit.lFs;
    px = interpolate(k, [0, 1], [fx, contentX(li) + 20 * u]);
    py = interpolate(k, [0, 1], [fy, winTop + pageTop + lineTops[li] + fit.lFs]);
  }
  if (cursor && notFound && isLoaded) {
    const k = progress(frame, t.loaded + 20, t.loaded + 40);
    const bx = winLeft + winW / 2;
    const by = winTop + pageTop + pageH * 0.78;
    px = interpolate(k, [0, 1], [px, bx + 150 * u]);
    py = interpolate(k, [0, 1], [py, by]);
  }

  const shimmer = (frame * 2.2) % 200;
  const bone = (w: number | string, h: number, extra: React.CSSProperties = {}): React.CSSProperties => ({
    width: w,
    height: h,
    borderRadius: h / 2.4,
    background: `linear-gradient(90deg, #e9eaec 0%, #f6f6f7 ${shimmer / 2}%, #e9eaec ${Math.min(shimmer / 2 + 25, 100)}%)`,
    ...extra,
  });

  const page404 = rise(frame, fps, t.loaded, 12);
  const big = slam(frame, fps, t.loaded);

  return (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          left: winLeft,
          top: winTop,
          width: winW,
          height: winH,
          opacity: Math.min(appear * 1.5, 1),
          transform: `translate(${jolt}px, ${(1 - appear) * 70 * u}px) rotate(${jolt * 0.02}deg) scale(${0.95 + 0.05 * Math.min(appear, 1)})`,
        }}
      >
        <div style={{...sk.win, position: 'absolute', inset: 0, borderRadius: Math.max(st.radius, 4) * 1.3 * u, background: c.win, overflow: 'hidden'}}>
          {/* tab strip */}
          <div style={{height: tabH, background: strip, display: 'flex', alignItems: 'flex-end', padding: `0 ${22 * u}px`, gap: 22 * u}}>
            <div style={{height: tabH, display: 'flex', alignItems: 'center'}}>
              <WindowDots size={18 * u} gap={10 * u} />
            </div>
            <div
              style={{
                height: tabH - 12 * u,
                width: Math.min(420 * u, winW * 0.45),
                background: c.win,
                borderRadius: `${14 * u}px ${14 * u}px 0 0`,
                display: 'flex',
                alignItems: 'center',
                gap: 12 * u,
                padding: `0 ${18 * u}px`,
                boxSizing: 'border-box',
              }}
            >
              <div
                style={{
                  width: 22 * u,
                  height: 22 * u,
                  borderRadius: bad ? 11 * u : 6 * u,
                  background: bad ? red : loading ? 'transparent' : p.accent2,
                  border: loading ? `${3 * u}px solid ${alpha(ink, 0.25)}` : undefined,
                  borderTopColor: loading ? p.accent : undefined,
                  transform: loading ? `rotate(${frame * 18}deg)` : undefined,
                  boxSizing: 'border-box',
                  flexShrink: 0,
                }}
              />
              <div style={{fontFamily: family, fontWeight: 600, fontSize: 23 * u, color: ink, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>
                {isLoaded ? (notFound ? `404 · ${domain}` : title || domain) : typed ? domain : cyr ? 'Нова вкладка' : 'New tab'}
              </div>
            </div>
            <div style={{height: tabH - 12 * u, display: 'flex', alignItems: 'center', fontFamily: family, fontSize: 30 * u, color: alpha(ink, 0.6)}}>+</div>
          </div>

          {/* toolbar: back, forward, reload, the address bar */}
          <div style={{height: barH, display: 'flex', alignItems: 'center', padding: `0 ${24 * u}px`, gap: 10 * u, borderBottom: `${2 * u}px solid ${c.divider}`}}>
            <Icon d={BACK} size={40 * u} color={alpha(ink, 0.75)} />
            <Icon d={FWD} size={40 * u} color={alpha(ink, 0.35)} />
            <div style={{transform: loading ? `rotate(${frame * 14}deg)` : undefined, display: 'flex'}}>
              <Icon d={RELOAD} size={40 * u} color={alpha(ink, 0.75)} />
            </div>
            <div
              style={{
                width: fieldW,
                height: 58 * u,
                marginLeft: 6 * u,
                borderRadius: 29 * u,
                background: field,
                border: `${3 * u}px solid ${bad ? red : focused ? p.accent : 'transparent'}`,
                boxShadow: focused ? `0 0 0 ${5 * u}px ${alpha(p.accent, 0.22)}` : undefined,
                display: 'flex',
                alignItems: 'center',
                gap: 10 * u,
                padding: `0 ${20 * u}px`,
                boxSizing: 'border-box',
                overflow: 'hidden',
              }}
            >
              <Icon d={LOCK} size={30 * u} color={alpha(ink, 0.6)} />
              <div style={{width: urlTextW, overflow: 'hidden', whiteSpace: 'nowrap'}}>
                <span
                  style={{
                    display: 'inline-block',
                    transform: `translateX(${-shift}px)`,
                    fontFamily: family,
                    fontWeight: 600,
                    fontSize: urlFs,
                    color: typed ? ink : alpha(ink, 0.45),
                  }}
                >
                  {typed || (frame < t.typeStart ? (cyr ? 'Пошук або адреса' : 'Search or type a URL') : '')}
                  <span
                    style={{
                      display: 'inline-block',
                      width: 3 * u,
                      height: urlFs * 1.1,
                      marginLeft: 2 * u,
                      verticalAlign: '-0.2em',
                      background: p.accent,
                      opacity: focused && frame < t.enter && (typing || Math.floor(frame / 8) % 2 === 0) && frame >= t.typeStart - 2 ? 1 : 0,
                    }}
                  />
                </span>
              </div>
            </div>
            <svg width={10 * u} height={34 * u} viewBox="0 0 8 30" style={{marginLeft: 'auto'}}>
              {[5, 15, 25].map((y) => (
                <circle key={y} cx={4} cy={y} r={2.8} fill={alpha(ink, 0.7)} />
              ))}
            </svg>
          </div>

          {/* the page */}
          <div style={{position: 'absolute', left: 0, top: pageTop, width: winW, height: pageH, background: page, overflow: 'hidden'}}>
            {loading ? (
              <div style={{position: 'absolute', left: 0, top: 0, height: 5 * u, width: `${loadK * 100}%`, background: p.accent, boxShadow: `0 0 ${10 * u}px ${p.accent}`}} />
            ) : null}
            {frame < t.enter ? (
              // a generic new tab: a search box and a few shortcuts
              <div style={{position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 40 * u}}>
                <div
                  style={{
                    width: pageW * 0.86,
                    height: 84 * u,
                    borderRadius: 42 * u,
                    border: `${3 * u}px solid #e2e3e6`,
                    boxShadow: `0 ${6 * u}px ${18 * u}px rgba(0,0,0,0.06)`,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 16 * u,
                    padding: `0 ${28 * u}px`,
                    boxSizing: 'border-box',
                    fontFamily: family,
                    fontWeight: 600,
                    fontSize: 30 * u,
                    color: '#9aa0a8',
                  }}
                >
                  <svg width={34 * u} height={34 * u} viewBox="0 0 24 24">
                    <circle cx={10.5} cy={10.5} r={6.5} stroke="#9aa0a8" strokeWidth={2.4} fill="none" />
                    <path d="M15.5 15.5 L21 21" stroke="#9aa0a8" strokeWidth={2.4} strokeLinecap="round" />
                  </svg>
                  {cyr ? 'Пошук або адреса' : 'Search or type a URL'}
                </div>
                <div style={{display: 'flex', gap: 34 * u}}>
                  {[p.accent, p.accent2, '#7c8db5', '#c7a6e8'].map((col, i) => (
                    <div key={i} style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 * u}}>
                      <div style={{width: 92 * u, height: 92 * u, borderRadius: 46 * u, background: '#f0f1f3', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
                        <div style={{width: 40 * u, height: 40 * u, borderRadius: 10 * u, background: col, opacity: 0.85}} />
                      </div>
                      <div style={{width: 70 * u, height: 12 * u, borderRadius: 6 * u, background: '#e6e7ea'}} />
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            {frame >= t.enter && !isLoaded ? (
              <div style={{position: 'absolute', left: padP, top: 30 * u, width: pageW, display: 'flex', flexDirection: 'column', gap: 22 * u}}>
                <div style={{display: 'flex', gap: 16 * u, alignItems: 'center'}}>
                  <div style={bone(46 * u, 46 * u, {borderRadius: 10 * u})} />
                  <div style={bone(200 * u, 22 * u)} />
                </div>
                {notFound ? null : <div style={bone('100%', Math.min(200 * u, pageH * 0.25), {borderRadius: 18 * u})} />}
                <div style={bone('82%', 40 * u)} />
                <div style={bone('64%', 40 * u)} />
                {[0.96, 0.9, 0.94, 0.7].map((w, i) => (
                  <div key={i} style={bone(`${w * 100}%`, 24 * u)} />
                ))}
              </div>
            ) : null}

            {isLoaded && !notFound ? (
              <>
                {/* site header */}
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    width: winW,
                    height: headerH,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 16 * u,
                    padding: `0 ${padP}px`,
                    boxSizing: 'border-box',
                    borderBottom: `${2 * u}px solid #ececec`,
                    opacity: rise(frame, fps, t.loaded - 2, 16),
                  }}
                >
                  <div style={{width: 44 * u, height: 44 * u, borderRadius: 11 * u, background: `linear-gradient(135deg, ${p.accent2}, ${p.accent})`}} />
                  <div style={{fontFamily: family, fontWeight: 800, fontSize: 27 * u, color: pageInk, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: pageW * 0.55}}>
                    {domain}
                  </div>
                  <div style={{marginLeft: 'auto', display: 'flex', gap: 14 * u}}>
                    {[70, 90, 60].map((w, i) => (
                      <div key={i} style={{width: w * u, height: 14 * u, borderRadius: 7 * u, background: '#dfe1e4'}} />
                    ))}
                  </div>
                </div>
                {fit.hero ? (
                  <div
                    style={{
                      position: 'absolute',
                      left: padP,
                      top: heroTop,
                      width: pageW,
                      height: fit.hero,
                      borderRadius: 18 * u,
                      overflow: 'hidden',
                      background: `linear-gradient(135deg, ${mix(p.accent2, '#ffffff', 0.25)}, ${mix(p.accent, '#ffffff', 0.2)})`,
                      opacity: rise(frame, fps, t.loaded, 18),
                    }}
                  >
                    <svg width={pageW} height={fit.hero} viewBox={`0 0 ${pageW} ${fit.hero}`}>
                      <circle cx={pageW * 0.78} cy={fit.hero * 0.32} r={fit.hero * 0.14} fill="rgba(255,255,255,0.75)" />
                      <polygon points={`0,${fit.hero} ${pageW * 0.3},${fit.hero * 0.38} ${pageW * 0.55},${fit.hero} `} fill="rgba(255,255,255,0.45)" />
                      <polygon points={`${pageW * 0.35},${fit.hero} ${pageW * 0.66},${fit.hero * 0.5} ${pageW},${fit.hero}`} fill="rgba(255,255,255,0.3)" />
                    </svg>
                  </div>
                ) : null}
                {title ? (
                  <div
                    style={{
                      position: 'absolute',
                      left: padP,
                      top: titleTop,
                      width: pageW,
                      fontFamily: family,
                      fontWeight: 800,
                      fontSize: fit.tFs,
                      lineHeight: 1.15,
                      color: pageInk,
                      opacity: rise(frame, fps, t.loaded + 2, 16),
                      transform: `translateY(${(1 - rise(frame, fps, t.loaded + 2, 16)) * 20 * u}px)`,
                    }}
                  >
                    {title}
                  </div>
                ) : null}
                {lines.map((l, i) => {
                  const k = rise(frame, fps, t.reveals[i], 16);
                  return (
                    <div
                      key={i}
                      style={{
                        position: 'absolute',
                        left: padP,
                        top: lineTops[i],
                        width: pageW,
                        fontFamily: family,
                        fontWeight: 400,
                        fontSize: fit.lFs,
                        lineHeight: 1.45,
                        color: i === 0 ? pageInk : pageMuted,
                        opacity: frame < t.reveals[i] - 1 ? 0 : Math.min(k, 1),
                        transform: `translateY(${(1 - Math.min(k, 1)) * 18 * u}px)`,
                      }}
                    >
                      {l}
                    </div>
                  );
                })}
              </>
            ) : null}

            {isLoaded && notFound ? (
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 18 * u,
                  padding: `0 ${padP}px`,
                  textAlign: 'center',
                }}
              >
                <div
                  style={{
                    fontFamily: family,
                    fontWeight: 800,
                    fontSize: 230 * u * (vertical ? 1 : 0.8),
                    lineHeight: 1,
                    letterSpacing: '-0.04em',
                    color: accentInk,
                    opacity: Math.min(big * 1.5, 1),
                    transform: `scale(${2 - Math.min(big, 1.1)}) rotate(${(1 - Math.min(big, 1)) * -8}deg)`,
                    textShadow: `0 ${10 * u}px 0 ${alpha(accent2Ink, 0.18)}`,
                  }}
                >
                  404
                </div>
                <div style={{fontFamily: family, fontWeight: 800, fontSize: 46 * u, color: pageInk, opacity: rise(frame, fps, t.loaded + 6, 16)}}>{title}</div>
                {lines.map((l, i) => (
                  <div
                    key={i}
                    style={{fontFamily: family, fontWeight: 400, fontSize: 32 * u, lineHeight: 1.4, color: pageMuted, opacity: rise(frame, fps, t.reveals[i], 16), maxWidth: pageW}}
                  >
                    {l}
                  </div>
                ))}
                <div
                  style={{
                    marginTop: 18 * u,
                    padding: `${16 * u}px ${34 * u}px`,
                    borderRadius: st.radius === 0 ? 0 : 40 * u,
                    background: accentInk,
                    color: '#ffffff',
                    fontFamily: family,
                    fontWeight: 800,
                    fontSize: 28 * u,
                    opacity: page404 * rise(frame, fps, t.loaded + 14, 16),
                  }}
                >
                  {homeLabel}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>

      {cursor ? (
        <>
          {t.click !== null ? <Ripple frame={frame} at={t.click} x={fieldX} y={fieldY} r={44 * u} color={alpha(p.accent, 0.85)} width={5 * u} /> : null}
          <Pointer x={px} y={py} size={46 * u} press={press} opacity={Math.min(appear * 1.5, 1)} />
          {t.click !== null ? <Sfx name="click" at={t.click} /> : null}
        </>
      ) : null}
      <Sfx name="keys" at={t.typeStart} dur={t.typeEnd - t.typeStart} />
    </AbsoluteFill>
  );
};
