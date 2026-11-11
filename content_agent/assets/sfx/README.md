# Sound effects for Shorts

From the Wyzowl SFX Kit (https://github.com/wyzowl/sfx-kit), CC0 1.0: public domain, no credit required. All
loudness-matched WAV, 48 kHz. `sources.json` lists the candidates per category with direct URLs.

| file | kit sound | sync point |
|---|---|---|
| whoosh.wav | whoosh-medium-soft | 0.229 s (the peak lands on the cut) |
| pop.wav | pop-medium-in | 0.011 s |
| click.wav | click-tap-soft | 0.009 s |
| keys.wav | keyboard-typing-steady-medium | 0 (looped while text types) |
| ding.wav | notification-success-soft | 0 |
| buzz.wav | notification-error-soft | 0 |

`content_agent.sound.write_sfx_bank` copies these into a project's `audio/sfx/`; the renderer starts each one
its sync point earlier (`SFX_LEAD` in `remotion/src/motion.tsx`).
