# PROMPT AGENT — шаг 4: l4media, свежесть RTP и синхронизация медиастатуса

Ты инженер медиастека: ingress, TCP/TLS framing, RTP/RTCP, Nginx, Janus, WebRTC. Работай в `l4media` и его тестах/документации; сначала определи фактический язык/build/test каждого компонента. Не назначай стек ingress по предположению. BFF/frontend изменения передавай отдельным владельцам.

Контекст: [общий отчёт](prompt_step4_stacks_overview.md), F5/F9. Не перезапускать сервисы и не менять logging/mountpoints/routes на production без отдельного разрешения.

## 1. Наблюдения, не смешивать с причиной остановки

- l4desk остановил FFmpeg по lease_expired; это подтверждённая причина завершения источника, не доказанный сбой Janus.
- В ingress для 773 в 10:54:00/10/20Z остаётся STREAMING при неизменных `RTP=3867`, `RTCP=4`, `4463 KB`. Существующее соединение и накопленный счётчик не доказывают актуальную передачу кадров.
- Janus в 10:53:32Z сообщил «stream with provided ID already exists», затем mountpoint пересоздан; есть предупреждение deprecated create API. Сам этот обработанный конфликт не объясняет stop спустя 20 с.
- Подробный Janus debug выводит тело create/watch с PIN. В отчёты переносить только redacted события, не сырые строки.
- Docker stdout l4media-nginx в выбранном окне пуст; фактическое расположение access/error логов отдельно проверить.

## 2. Задачи

1. До правки воспроизвести stale media: подключение остаётся открытым, RTP прекращается, RTCP/transport heartbeat может продолжаться. Тест должен показать неверное/неоднозначное значение live на существующем поведении.
2. Согласовать `/stats`/status контракт с BFF: transport_connected, last_rtp time/age, счётчики/дельты, stream/connection epoch, stale deadline. Названия полей предложить и согласовать, не внедрять скрыто. RTCP или TCP keepalive не обновляет last RTP/frame freshness.
3. Развести состояния route exists / connected / receiving fresh media / stale / disconnected. Если STREAMING остаётся техническим состоянием транспорта, обеспечить отдельную явную freshness; не менять смысл enum молча. При неизвестных метриках возвращать unknown, не live.
4. Проверить атомарные snapshot счётчиков/time, монотонные интервалы, reconnect/route update, повторные SN, завершение старого connection и поздние callbacks. Старые счётчики/эпоха не должны маркировать новое соединение живым.
5. Согласовать terminal stopped с media state: событие текущей эпохи имеет приоритет для UI; поздний ingress snapshot не воскрешает источник. Не назначать ingress владельцем lease и не делать server revoke из эвристики одного media timeout без утверждённой политики.
6. Вместе с BFF ревизовать mountpoint create/reuse/destroy и PIN lifecycle: существующий ID не всегда stale; проверять владельца/эпоху перед destroy. Повтор stop/release не должен ломать новую сессию или чужих viewers. Обновление deprecated API — отдельный совместимый diff с тестами, не безусловная причина массового recreate.
7. Предложить redaction/уровень логов Janus и прокси, исключающий PIN/admin secret/JWT/cookie/payload. Сохранить безопасные request/stream IDs, transition/reason и ошибки. Не менять production logging в рамках диагностики; подготовить локальный diff и rollback.
8. Проверить cert↔SN trust boundary и скрытость management API в рамках разрешённого репозитория. Не открывать admin API наружу ради теста; не менять TLS/ACL как обход проблемы renewal.

## 3. Проверки

- Обнаружить и выполнить все релевантные тесты/build ingress; добавить regression stale-RTP, RTCP-only, socket-open idle, reconnect, simultaneous old/new epoch, route missing/duplicate SN и malformed framing.
- Contract fixture `/stats` потребляется BFF и frontend; backward compatibility старого snapshot проверяется явно. После expiry freshness состояние stale/unknown появляется в согласованный срок, несмотря на ненулевые накопленные счётчики.
- Nginx config validation и проверка Janus API на локальном/согласованном стенде; success mountpoint create/reuse/destroy, повторные вызовы, безопасный PIN handling без вывода PIN.
- E2E ≥120 с в динамической тестовой сцене: fresh RTP + decoded frames; остановка источника при живом proxy transport → UI перестаёт считать видео live в согласованный stale timeout. Счётчики браузера не заменять одним HTTP 200.
- Негатив: late old stats, Janus reconnect, packet loss, auth failure, old destroy после нового start; никакого выключения lease watchdog.

## 4. Handoff

Верни schema `/stats`, измеримый stale timeout и компромиссы, media state machine, test evidence, config diff/redaction policy, API compatibility с установленным Janus. Укажи владельца изменений BFF/UI и невыполненные E2E. Не утверждать, что новая метрика исправляет первопричину F1: это отдельная часть честного отображения состояния.