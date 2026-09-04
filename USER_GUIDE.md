# Руководство пользователя

MVP 0.1: папка задачи → индекс → Find Object → Timeline / Events Around → исходник. Не диагноз инцидента.

## Установка

Нужен Sublime Text 4 (сборка 4050 или новее). Плагин работает на Python 3.8.

Каталог пакета в Sublime должен называться `RedVirtLogViewer` (без дефисов). Симлинк с репозитория:

```bash
ln -sfn /path/to/red-virt-log-viewer ~/.config/sublime-text/Packages/RedVirtLogViewer
```

Zip для коллеги (без `.git`, без клиентских логов, без рабочего кеша):

```bash
cd /path/to/red-virt-log-viewer
zip -r /tmp/RedVirtLogViewer.zip \
  RedVirtLogViewer.py core parsers ui \
  *.sublime-commands *.sublime-menu *.sublime-keymap *.sublime-settings \
  RedVirtLog.sublime-syntax \
  licenses THIRD_PARTY_NOTICES.md README.md USER_GUIDE.md ARCHITECTURE.md
```

Распаковать в `Packages/RedVirtLogViewer`. Тесты (`tests/`) в zip не обязательны: они для `python3.8 -m unittest`. Публикация в Package Control не входит в MVP. Лицензия собственного кода пока не задана; копия Apache-2.0 для шаблонов Engine/VDSM должна остаться в `licenses/`.

Перезапустите редактор. Команды — Command Palette, префикс `RED Virt`. Пункты Tools открываются **кликом**, не наведением.

## Сценарий

1. **File → Open Folder** на каталог **одного обращения**. Не весь `tickets/`. Индекс в фоне, вкладка Session.
2. Кеш: `~/.cache/red-virt-log-viewer/roots/<ключ>/`. Повторное открытие не перечитывает неизменённые файлы.
3. `"tickets_root"` необязателен: сам корень всех тикетов не индексируется (ни Open Folder, ни Open Support Folder).
4. **Find Object** — UUID или имя из QEMU launch. Enter открывает исходник.
5. **Show Timeline** — после выбранного объекта (или запрос UUID). Поле `start|end` с явным поясом (`2026-08-28 13:00:00+0000|2026-08-28 14:00:00+0000`) или пусто — все **привязанные к UTC** события объекта, страница `page_size`. Интервал `[начало, конец)`. Без UTC в окно не входят (счётчик untimed).
6. **Events Around** — курсор на строке результата с временем или в проиндексированном файле. Панель ±1 / ±5 / ±15 минут. Не подставляется «сейчас» с компьютера.
7. Journal без года: задайте оба `journal_year` и `journal_utc_offset` (`Z`, `+0800`, `+03:30`) и **Rebuild Index**. Год с часов машины не берётся. Один год на сессию; переход Jan/Dec не угадывается.

Имя не уникально. QEMU май и VDSM август с одним UUID — идентичность, не один инцидент.

## Лимиты

Не обещать разбор многогигабайтных сборов. Фактически: `page_size` (страница результатов), `max_line_bytes`, `direct_open_max_bytes` (большие и сжатые файлы открываются фрагментом). Буквальный поиск читает файлы, не SQLite. Квота объёма кеша не измерялась и не включена.

## Чеклист после установки

- Сессия: Open Folder на один сбор; вкладка Session; корень `tickets_root` не индексируется.
- Индекс: повторное открытие без лишнего разбора; Rebuild Index; Clear Session Cache только для этого ключа; Cancel во время индекса.
- Search Text: буквальный `.*` не regex; gzip/xz; Enter → исходник.
- Find Object: UUID и имя из QEMU launch; два UUID с одним именем раздельно; диск UUID не ВМ.
- Timeline / Around: `start|end` или пусто; untimed в шапке; Around не от часов ПК.
- Journal: без настроек нет UTC; после года+offset и Rebuild — есть.
- Палитра не глотает поле ввода (короткая задержка перед input panel).

## Чего нет

- Хосты, фильтры узла/уровня, объекты Engine как сущности.
- Предразбор всех номеров в `tickets/`.
- Postgres, Package Control.
- Автодиагноз, распаковка `.tar.gz`.

## Проверка ядра без редактора

```bash
python3.8 -m unittest discover -s tests -v
```

Клиентские сборы и `log-parser-samples-BosLPH` в репозиторий не входят. Если каталог образцов есть локально, optional-тесты не skip, а выполняются.
