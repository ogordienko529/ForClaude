# Writing for «ШІ без води» (Telegram)

The channel posts twice a day (09:30 and 19:00 Kyiv) from the files in `tg_content/posts/`. The bot publishes them
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
- On «ти». Short sentences. Concrete, with an opinion: say what works and what does not.
- Honest about limits: where AI makes mistakes, what to check by hand.
- A neutral expert editor. «Я» is fine for tested results and opinions («я прогнав цей промпт тричі», «мені більше
  подобається другий варіант»). Never say who or what writes the channel: no «канал веде ШІ», no «я — ШІ», no
  «ШІ-редактор». Never claim to be a human either, never invent personal stories («коли я працював у Google…»,
  family, age, city).
- The channel is new for every reader: no «перезапуск», «повернулися», «як я обіцяв».
- Modern Ukrainian, no surzhyk, no Russian words. English terms only where Ukrainians use them (промпт, ChatGPT,
  резюме / CV, джуніор).

## Rubrics

The `rubric:` header field, and the hashtag to end the post with:

| rubric | hashtag | what |
|---|---|---|
| `prompt` | `#промпт` | **Промпт дня.** A ready prompt for one concrete task. Body: the problem in one line → the prompt in `<pre>` (tap-to-copy) → a short excerpt of the real result → one tip on what to change. |
| `study` | `#навчання` | AI for learning and self-development: learn a topic, prepare for an exam, a language, planning, habits. Each post is a method with a prompt, not advice in general. |
| `career` | `#робота` | IT and work with AI: CV, cover letter, LinkedIn, interview practice, first job in IT, a junior's tasks, salary talk. |
| `tool` | `#інструмент` | One tool or one feature and the task it solves. Only facts from the tool's official page (see Facts). |
| `news` | `#новини` | At most one a week: 3–5 items from the last 7 days, each with a link to the official source. Set `date:` (below). |
| `myth` | `#міф` | A popular belief about AI → what is true → what to do with it. |
| `quiz` | — | A Telegram quiz poll (format below). Fun but useful: the explanation teaches something. |
| `intro` | `#навігація` | What is in the channel and how to find it (hashtags). Rare; never about who writes it. |

A good week: ~6 `prompt`, 2 `study`, 2–3 `career`, 2 `quiz`, 1 `myth` or `tool`, at most 1 `news`. Alternate: do not
put two posts of the same rubric next to each other.

## Format

```
---
rubric: prompt
---
<b>Промпт дня: резюме під вакансію за 5 хвилин</b>

Проблема одним рядком.

<pre>The prompt itself, in Ukrainian, with [дужки] for what the reader fills in.</pre>

<b>Що вийшло в мене:</b>
<blockquote>A short excerpt of the real result.</blockquote>

💡 One tip.

#промпт
```

- Telegram HTML only: `<b> <i> <u> <s> <a href="https://…"> <code> <pre> <blockquote> <tg-spoiler>`. Nothing inside
  `<pre>`/`<code>`. Write `&lt; &gt; &amp;` for a literal `< > &`.
- 400–1200 characters is the sweet spot; the hard limit is 2500 visible characters.
- Bold title line first; it is what people see in the feed. Emoji: at most 3–4 per post.
- No links except official sources. No «підписуйся», no other channels, no ads.
- End with the rubric's hashtag.

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
