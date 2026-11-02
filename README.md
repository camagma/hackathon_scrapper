# Devpost reminder bot

Python 3.11+. Сейчас выполнен **шаг 1 из 7: инспекция источника**.
Загрузка с фильтрами, SQLite, напоминания, Telegram, Actions и CSV будут
добавляться отдельными шагами после ревью.

## Проверка источника — 2 ноября 2026

Проверен реальный ответ `https://devpost.com/api/hackathons?page=1`:
HTTP 200, `application/json; charset=utf-8`. Исходный ответ сохранён в
[`inspection/response.json`](inspection/response.json), правила — в
[`inspection/robots.txt`](inspection/robots.txt).

Это неофициальный публичный endpoint; его структура может измениться.
HTML `https://devpost.com/hackathons` при прямом запросе вернул 403;
страница открылась веб-инструментом, но он не показал сетевые запросы JavaScript.
Поэтому связь endpoint с текущим frontend не подтверждена сетевой трассировкой;
сама структура JSON проверена прямым запросом, а не взята из примера.

Ответ содержит `hackathons` (массив) и `meta`:
`{"total_count": 14229, "per_page": 9, "fuzzy": false}`.
Проверена только первая страница: 9 записей, все со статусом `open`.
Значение для upcoming и параметры серверных фильтров пока не проверены.

| Поле | Реальная структура / смысл |
| --- | --- |
| `id` | Число, например `31302` |
| `title` | `PayPal AI Hackathon` |
| `url` | `https://paypalaihackathon.devpost.com/` |
| `displayed_location` | Объект `{"icon": "globe", "location": "Online"}` |
| `open_state` | Строка; в этой выборке `open` |
| `submission_period_dates` | Строка `Oct 01 - Nov 12, 2026` |
| `time_left_to_submission` | Описательный текст: `10 days left`, `about 1 month left` |
| `themes` | Массив объектов `{id, name}`; `Machine Learning/AI` имеет id `6` |
| `prize_amount` | Строка с HTML: `$<span data-currency-value>67,500</span>` |
| `prizes_counts` | Объект с числовыми `cash`, `other` |
| `registrations_count` | Число зарегистрированных, не срок регистрации |
| `organization_name` | Строка |
| `featured`, `winners_announced`, `invite_only`, `managed_by_devpost_badge` | Логические значения |
| `eligibility_requirement_invite_only_description` | Во всех 9 записях `null` |
| `thumbnail_url`, `analytics_identifier` | Строки |
| `submission_gallery_url`, `start_a_submission_url` | Строки-ссылки; переходить по ним бот не будет |

**Отдельного registration deadline в проверенных записях нет.**
Бот будет использовать конец периода подачи проектов (`submission_period_dates`)
и явно писать в сообщениях «дата окончания приёма проектов».
Это календарная дата: источник не предоставляет точное время или часовой пояс.
Нельзя выдавать её за точный timestamp или вычислять дату из приблизительного
`time_left_to_submission`. Самостоятельного структурированного `start_date`
также нет: начало и конец предстоит извлекать из диапазона.

В robots.txt общий блок `User-agent: *` содержит пустой `Disallow`, то есть
не запрещает этот путь. Отдельно запрещены BLEXBot, Omgilibot, Omgili,
ImagesiftBot и Bytespider. Это правила обхода, а не гарантия доступности API.
Для инспекции сделано три прямых запроса: robots.txt, HTML списка и одна
страница JSON. Проекты и профили участников не запрашивались.

Выбран JSON списка: один запрос даёт сразу несколько событий, что уменьшает
нагрузку и позволяет не разбирать HTML отдельных страниц. Исходный ответ
оставлен целиком для проверки полей и будущей офлайн-отладки. Цена с HTML
потребует очистки; диапазоны дат — явного разбора с обработкой ошибок.

## Повторить инспекцию

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python inspect_endpoint.py --offline inspection/response.json
```

Один свежий запрос списка после проверки robots.txt:

```powershell
python inspect_endpoint.py
```

Скрипт печатает три исходные записи без изменения полей, метаданные и полный
список найденных ключей. При HTTP-ошибке останавливается без повторных попыток.

## Следующие шаги

2. Получение и фильтры, вывод в консоль.
3. SQLite и идемпотентные обновления.
4. Напоминания за 7 и 1 день, pytest без сети.
5. Telegram через HTTP `sendMessage`, секреты из окружения.
6. Ежедневный GitHub Actions с сохранением SQLite, инструкция cron.
7. CSV через `csv`, `utf-8-sig`, временный каталог; Telegram `sendDocument`,
   отдельные тесты и расписание экспорта (по умолчанию еженедельно).
