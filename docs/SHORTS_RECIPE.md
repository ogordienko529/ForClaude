# Short videos about AI tips: the edit recipe (November 2026)

From a study of AI-tips / prompt Shorts, Reels and TikToks that perform well, made for the Telegram channel
«ШІ на старті» (@shi_start_ua). Most numbers come from vendors' blogs (Opus, Quso, vidIQ, CapCut): orientation, not
proof. The channel's test Shorts live in `tg_content/videos/<slug>/` (voice) and `content_projects/<slug>/`
(storyboard, renders).

## The channel's format (owner's choice, November 2026)
- **Opener:** the topic first, the series promise second: «Рецепт борщу може вкрасти твій пароль. Пояснюю за 30
  секунд.», «Детектор ШІ — не доказ, що текст писав чат. Пояснюю за 30 секунд.» The first words are the hook, so
  they carry the surprise or the pain; the promise only confirms the format. The picture under it is already the
  topic in motion. Storyboard `"countdown": true` shows a «⏱ 0:29» pill counting down the real seconds left, so
  the video must really be ≤ 30 s.
- **Topics:** the viewer's pains first (детектор ШІ, НМТ, сесія, курсова, резюме, співбесіда), explainers second.
- **Ending:** the last line asks for a comment («А тебе детектор колись ловив? Напиши в коментарях.») and the
  `comment` bubble shows the same question.
- **Pace:** scripts of ~330–400 characters (7 lines), voice `"voice_tempo": 1.12–1.22` (quicker, pitch kept, no
  re-voicing); check `content_agent voice <slug>` says ≤ 30 s before rendering.
- **Light humour:** one or two small jokes per video, about the thing, never about people: «"мол" і "око" —
  звучить як ім'я ельфа», «як груповий чат курсу: про що домовились — ніхто не пам'ятає», «борщ із секретним
  інгредієнтом». Read the joke aloud with «ШІ» said as «Ші»: «і в ШІ» sounds like «і вші».
- **One text at a time:** `"captions": false` on kinetic scenes and on scenes whose UI shows the spoken words.
- **The series and the way to the channel are always on screen.** These storyboard keys work in `shorts` only:
  - `"series": "ШІ за 30 · №5"` (≤ 24 characters) shows a plaque in the accent colour right of the countdown.
  - `"handle": "@shi_start_ua"` (≤ 24) adds a «✈ Telegram · @shi_start_ua» row under it. Scenes move down by 4 % of
    the height to clear that row.
  - With `countdown`, the plaque and the handle slide in once the countdown has settled, so the hook frame stays
    clean.
  - `"comment": "Що відповів твій чат?"` (≤ 48) pops a «💬 … 👇 напиши в коментарях» bubble over the last scene,
    above the captions. This is the ending task that brings comments.
- **The call to action is the channel's post, not a static card.** The `tgpost` scene shows a Telegram-like channel
  view:
  - props: `title` (≤ 60), `prompt` (≤ 160, a monospace tap-to-copy block), `channel` (default «ШІ на старті») and
    `tag` (e.g. «#зролика»);
  - on screen: the channel header with the round «Ш І» avatar, then the post;
  - motion: the prompt types in, a fingertip taps the block (on cue 0, else at 55 %), the toast «Скопійовано в буфер
    обміну» comes up, and the tag pulses.

  Use it instead of the kinetic «у Telegram @shi_start_ua» cards, with `"cues": ["телеграм"]` so the tap lands
  on the word, and show the prompt of the channel's post (shortened to 160 characters if needed).

## Hook (0–2 s)
- The first frame already shows the result or the mistake, in motion, no fade-in: a CV covered in ❌, a red error,
  a citation stamped «FAKE». Not a title card.
- 3–6 words in the upper third; red / green contrast.
- «Stop doing X» works only together with the mistake shown on screen; pain first, AI as the fix.

## Picture
- Drawn UI that looks like a real app: a phone with a chat, a code editor or terminal, a browser page, a document.
- The prompt types in with a caret; a finger tap on send; a punch-in zoom onto the key line ~0.2 s before the voice
  says it; a marker / arrow / circle on it; «погано / добре» split with ❌ / ✅ stamps.
- A new picture every 1.5–3 s (10–14 visual events in 25 s); faster than ~1.2 s reads as noise.
- One movement = one idea. Effects without meaning and text too fast to read are «too much».
- UI in the upper 40–60 % of the 9:16 frame, captions under it; hide captions while the UI types the same words.

## Captions
- 2–4 words at a time, karaoke highlight, at most two lines, the key word yellow and ~15 % bigger.
- Centre or upper middle; never the bottom ~20 % or the right ~15 % (platform buttons).

## Sound
- Music 120–140 BPM, ducked under the voice.
- One sound, one job: whoosh = zoom / cut, pop / click = an element appears, keys = typing, ding = right,
  buzz = wrong. The peak lands on the frame of the action.
- Voice 150–170 words a minute (Ukrainian: ~2.3–2.6 words a second, 55–65 words in 25 s); short sentences.
  ElevenLabs: speed 1.05–1.15, stability a little below default.

## Structure
- 15–30 s (the channel: ≤ 30 s, the countdown shows it). An open loop («3 перевірки — третя найважливіша») that pays off; a loop ending where the last frame
  matches the first.
- The call to action is a 1.5 s sticker in the middle («Більше — в Telegram, лінк у профілі»), not the ending.
  Shorts links are not clickable: the handle on screen and the link in the profile.

## Avoid
- The same template in every video, a synthetic voice with no pauses, pictures unrelated to the words, clichés
  («feels illegal»): YouTube's «inauthentic content» rule (since 15.07.2025) and TikTok's unoriginal-content rule hit
  exactly this. Real tests (a real answer, a real error) and varied layouts help.

## A 25-second template
| s | Screen | Voice | Sound |
|---|---|---|---|
| 0–2 | The mistake, full frame, sharp zoom | the hook line | hit + buzz |
| 2–4 | «you ask / ask like this» split | why it matters | whoosh |
| 4–7 | Phone chat, the prompt types in | the key phrase of the prompt | keys |
| 7–10 | Zoom + marker on 3 words | «the secret is these words» | pop ×3 |
| 10–13 | The answer streams in, the key line highlighted | what it gives | ding |
| 13–16 | Counter «2 / 3» | «but the best is the third» | riser |
| 16–19 | The fix → ✅ | the payoff | click + ding |
| 19–21 | Telegram sticker over the result | one sentence | pop |
| 21–25 | Back to the first frame | the loop line | music into the hook |
