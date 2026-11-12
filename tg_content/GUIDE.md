# Writing for «ШІ на старті» (Telegram)

The channel posts twice a day (09:30 and 17:15 Kyiv) from the files in `tg_content/posts/`. The bot publishes them
in file-name order; nobody reviews them first. So every post you write here goes out as is. This file is the brief
for whoever writes them: a person, a Claude session, or the `tg-content.yml` workflow.

## The promise

**ШІ для навчання і першої роботи в IT.** Practical AI in Ukrainian for the road «вчуся → шукаю першу роботу →
перші місяці на роботі». A reader should be able to use something from each post the same day. No motivation
talk, no hype, no news for the sake of news. General AI news, memes and tools for senior developers are other
channels' job.

**Reader:** a Ukrainian, 17–30: a student, someone moving into IT (QA, analytics, development, design, PM), a
junior in the first year. Uses ChatGPT, Gemini or Claude on the free plan, often from a phone.

**What a model alone does not give them, and the channel does:** the Ukrainian context (vacancies on Djinni, Work.ua
and DOU, Ukrainian universities, НМТ, Дія.Освіта), tested results instead of promises, «до / після» on realistic
examples, and honest «що перевірити руками».

**Voice:**
- On «ти». Short sentences. Concrete, with an opinion: one sentence of opinion or dry humour right after the title
  («Найчастіша помилка тут — просити ШІ "покращити" резюме»). No jokes about people.
- Honest about limits: where AI makes mistakes, what to check by hand.
- A neutral expert editor. «Я» only in the present tense («раджу», «перевіряю»): the Ukrainian past tense has a
  gender. Never say who or what writes the channel: no «канал веде
  ШІ», no «я — ШІ», no «в мене теж». Never claim to be a human, never invent personal stories (work, family, age).
- The channel is new for every reader: no «перезапуск», «повернулися», «як я обіцяв».
- Modern Ukrainian, no surzhyk, no Russian words. English terms only where Ukrainians use them (промпт, ChatGPT,
  резюме / CV, джуніор).

**Claude first:** most examples use Claude (name it: «встав у Claude», «попроси Claude»), others where natural
(ChatGPT, Gemini). The channel teaches how to talk to Claude well; tips about prompting follow Anthropic's official
«Prompting best practices» (https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)
and link the section they use. Never imply the channel is Anthropic's or endorsed by it.

## What the data says (competitor study, 2,120 posts of 30 channels, November 2026)

- Short wins: the channels readers react to most keep 73–84 % of posts under 600 characters; the top 10 % of posts
  by reactions have a median of ~550 characters. Posts over 1,500 characters almost never reach the top.
- The first line tells the whole story. Title lines up to 50 characters get more reactions than longer ones.
- A Ukrainian angle in the title (Djinni, DOU, Work.ua, НМТ, a Ukrainian university, Ukrainian law) gets ~1.6× the
  reactions. Memes and curious stories get reactions; how-to posts get views but few reactions, so judge them by views.
- Model-release news under-performs; ads get almost no reactions.
- Two posts a day is enough; more posts do not mean more readers. 19:00 was the weakest hour, 10:00–17:00 and
  20:00 the strongest; weekends do better than weekdays.
- The niche is empty: of 710 posts in nine Ukrainian AI channels, one is a practical post about AI for a CV,
  interview, study or a first job.

## Rubrics

The `rubric:` header field, and the hashtag to end the post with (one hashtag):

| rubric | hashtag | what |
|---|---|---|
| `prompt` | `#промпт` | A ready prompt for one concrete task, built like the example below: what you get → who it helps → «Як зробити:» → the prompt in `<pre>` (tap-to-copy, ≤ 350 characters) → «Що вийде:» → 💡 one tip. 600–1000 characters. |
| `study` | `#навчання` | AI for learning: a method with a prompt (exams, НМТ, сесія, a language, planning). 600–1000 characters. |
| `career` | `#робота` | CV, cover letter, LinkedIn, interview practice, first job in IT, salary talk — with the Ukrainian market in the title when possible. 600–1000 characters. |
| `tool` | `#інструмент` | One tool or one feature and the task it solves. Only facts from the tool's official page (see Facts). |
| `explain` | `#простослова` | Something people hear about but few understand (MCP, agents, tokens, the context window, prompt injection), in plain words with one analogy → what it changes for a student or a junior → what to do today, often a prompt. Official links. 600–1000 characters. |
| `news` | `#новини` | Rare: only as «what changes for a student or a junior today», with official links. Set `date:`. |
| `myth` | `#міф` | A popular belief about AI → what is true → what to do. At most 600 characters, at most 3 bullets. |
| `quiz` | — | A Telegram quiz poll (format below). At most one in any 14 posts. |
| `intro` | `#навігація` | What is in the channel and how to find it (hashtags). Rare; never about who writes it. `pin: yes`. |

**Short posts** (250–500 characters, no prompt block): one idea — a mistake, a «до / після», an opinion on «ШІ і
джун», a curious fact with a source. Use rubric `myth`, `career`, `study` or `tool` as fits.

**A week (14 slots, 09:30 and 17:15):** 4 `prompt`, 1 `explain`, 2 `career` (one with a Ukrainian market fact and
its link), 2 `study`, 2 short posts, 1 `tool`, 1 `quiz` (or a two-reaction vote), 1 «ШІ і джун». Never two posts of
the same rubric in a row. Once a week end a post with a two-reaction vote («❤️ — вже пробував, 👀 — ще ні»); promise
nothing.

**With a video:** a Short that says «більше — у телеграм-каналі» on a new topic gets its post the same day: an
`explain` (or `prompt`) post with `date:` set to the day the video goes up, so it leads the morning slot. The
videos' scripts live in `tg_content/videos/<slug>/voice.json`.

## Clear first (the owner's verdict on the first posts: «дуже важко зрозуміти»)

The reader opens the post on a phone between two other things. If a sentence needs reading twice, the post failed.
Short is good, but never by squeezing: cut topics, not words.

- **Explain like a message to a friend** who has never used AI for this: what they get, why it helps, how to do it.
- **Say who it is for and when it helps** in the first two lines («Перед сесією…», «Коли шукаєш першу роботу…»).
- **«Як зробити:»** 2–3 numbered steps in plain words (open any chat, paste the prompt, put your text instead of the
  brackets). Do not assume the reader knows where to paste anything.
- **«Що вийде:»** one or two plain sentences about what the reader will get. Quote real output only when a stranger
  understands it without context; never paste an excerpt of a made-up example that needs decoding.
- **No unexplained jargon:** STAR, стек-трейс, ATS, онбординг, BETWEEN, «прогін» — either say it in normal words
  or explain it in a few words in brackets. English only where Ukrainians say it in English (ChatGPT, промпт, CV).
- **One post = one task.** No «до / після» riddles, no labels the reader must learn (🧪, ⚠️ Де ламається).
- Test: read it as a first-year student who uses ChatGPT for homework. Could they do it right now? If not, rewrite.

## Format

```
---
rubric: study
---
<b>ШІ зробить тест з твого конспекту</b>

Перечитуєш конспект і здається, що все знаєш? Перевір це за 10 хвилин, перш ніж іти на іспит.

<b>Як зробити:</b>
1. Відкрий будь-який ШІ-чат: ChatGPT, Gemini чи Claude.
2. Скопіюй промпт нижче, а замість дужок встав свій конспект.
3. Відповідай на питання по одному.

<pre>Ось мій конспект: [встав текст]. Зроби тест на 10 питань тільки за цим текстом. Став по одному питанню й чекай на відповідь. Після кожної скажи, правильно чи ні, і покажи рядок з конспекту. В кінці дай список моїх помилок.</pre>

<b>Що вийде:</b> чат питатиме по черзі, а після помилки покаже, де в конспекті правильна відповідь. Одразу видно, що
ще треба повторити.

💡 Якщо чат питає про те, чого в конспекті немає, пропусти питання: він узяв його не з твого тексту.

#навчання
```

- The title line: at most 60 characters, says plainly what the reader gets («ШІ зробить тест з твого конспекту»,
  «Резюме під вакансію за 5 хвилин, без вигадок»). Never start with a rubric label such as «Промпт дня:».
- Telegram HTML only: `<b> <i> <u> <s> <a href="https://…"> <code> <pre> <blockquote> <tg-spoiler>`. Nothing inside
  `<pre>`/`<code>`. Write `&lt; &gt; &amp;` for a literal `< > &`.
- At most 1000 visible characters (myth: 600). Emoji: at most 3 per post.
- No links except official sources and the channel's own posts. No «підписуйся», no other channels, no ads.
- End with the rubric's one hashtag.

**Quiz** (a Telegram quiz poll; no text below the header):

```
---
rubric: quiz
question: Що з цього ШІ-чат НЕ вміє без підключеного пошуку?
options:
- Перекласти текст
- Знати сьогоднішній курс долара
- Скласти план навчання
correct: 2
explanation: Модель знає світ лише до дати навчання. Свіжі цифри дає тільки пошук.
---
```

Question ≤ 300 characters, 2–10 options ≤ 100 each, `correct` is the option number (1 = first), explanation ≤ 200.
Plain text, no tags.

**Dated posts:** `date: YYYY-MM-DD` (Kyiv) holds a post until that day and then sends it before the queue; two
days late it is skipped as stale. Use it for news and anything tied to a day.

## Facts

The post goes out unchecked, so:
- **Prompts:** run every prompt yourself before writing the post and quote the real output (shortened). Never
  describe a result you did not get.
- **No numbers you cannot source:** no prices, limits, model versions, release dates, user counts or study results
  unless you checked them on the official page in this session; then link that page. «За дослідженнями…» without a
  link is not allowed.
- **Tools:** name the big general ones (ChatGPT, Gemini, Claude, Copilot) without claims about plans or prices. A
  feature you name must exist on the free plan or be marked «у платній версії».
- **Advice that touches law, health or money:** general and careful, «перевір у фахівця» where it matters.
- **Quizzes:** only answers that are true now and will stay true for months.

## Words that give a machine away

The check (`python -m tg_channel queue`) blocks the phrases in `STOP_PHRASES` in `tg_channel/feed.py` («у сучасному
світі», «варто зазначити», «давайте розберемося», «ключову роль», «революційний», «підсумовуючи» …). Also avoid: three
adjectives in a row, «це не просто X, це Y», rhetorical questions as openers, ending on a moral.

## Files

- `tg_content/posts/NNNN-short-slug.md`, four digits, continuing from the highest number. The bot posts them in
  that order. Never rename or renumber a file: its name is its id, and a renamed published post goes out again.
- Before writing, read the last ~30 posts so topics do not repeat.
- Check: `python -m tg_channel queue` (exit code 0, no `✗` lines). With the bot's memory
  (`--state state/state.json`) it also leaves out what is already published.
- The channel's name and description: `tg_content/profile.json`. The bot applies a change on its next run.
