# PROMPT AGENT — шаг 4: MenuBuilder UI, единая сессия и достоверное состояние видео

Ты Senior Frontend инженер: React 19, TypeScript strict, Vite, Ant Design v6. Работай только в `MenuBuilder/frontend`, тестах и документации frontend. Бэкенд, app1 и MQTT-клиент не изменяй; запросы на контракты передавай их владельцам.

Обязательный контекст: [общий отчёт](prompt_step4_stacks_overview.md), F3/F4/F5; [BFF](prompt_step4_agent_menubuilder_backend.md). Не выполнять deployment, команды терминалу или подключение к рабочей аренде без отдельного разрешения.

## 1. Что уже известно

- HTTP keepalive выполняется каждые 5 с в `src/routes/video-surveillance.tsx`; WS keepalive — независимо в `src/hooks/useRemoteControl.ts`.
- `disable()` remote control отправляет WS release и best-effort HTTP DELETE. BFF дополнительно делает cleanup; серверные логи подтверждают освобождение общей lease в 10:55:01Z и HTTP keepalive этой же lease через ~1,3 с → 404.
- `stopped` дошёл до BFF в 10:53:53Z; получение/применение браузером ещё не доказано.
- catch HTTP keepalive останавливает таймер и показывает сообщение, но сам не завершает media/control session. HTTP status сохраняется interceptor: не исправлять несуществующую «потерю response» без воспроизведения.
- Защита `if (streamMode && streamMode !== "desktop")` разрешает input при unknown mode. Scope=input сам по себе не подтверждает desktop.

## 2. Ревизия и реализация

1. Исследовать `src/routes/video-surveillance.tsx`, `src/hooks/useRemoteControl.ts`, API DTO, `VideoPlayerScreen`, `RemoteControlOverlay`, обработчики stream_state/status и media lifecycle. Зафиксировать, кто владеет lease, таймерами, WS, player и переходом scope.
2. До правки добавить воспроизведение с fake timers и контролируемыми promises: stream lease → enable input с тем же ID → disable input/release → следующий HTTP tick. Отдельно воспроизвести stopped текущей эпохи и late response старой.
3. Согласовать с app1/BFF продуктовую семантику «отключить ввод» против «завершить видео». Если используется общая lease, hook не должен незаметно уничтожать её при живом просмотре. Если API не умеет detach/downgrade, запросить контрактное решение; не изобретать несуществующий endpoint.
4. Организовать одного владельца жизненного цикла/generation: отмена таймеров до release; bounded cleanup; нет overlap HTTP renewal; ответы и события проверяются по device/lease/stream epoch. Размонтирование, смена терминала, повторный start/stop и StrictMode не оставляют таймеров/WS.
5. Согласовать cadence renewal и роль WS heartbeat: транспортный heartbeat и продление lease — разные обязанности. Не удалить один канал так, чтобы просмотр без remote input перестал продлеваться. После teardown не начинать новый запрос старой сессии; уже отправленный безопасно игнорировать по generation.
6. Потеря текущей lease (согласованные 404/403/409) → один переход session ended, input disabled, остановка её renewal/WS/player, понятное сообщение. Не зациклить retry и не переоткрывать авторизацию автоматически. Temporary timeout/network error отображать иначе, с ограниченным восстановлением по контракту.
7. Обработать terminal stopped/failed вместе с reason и IDs: не ждать очередного HTTP 404. Старое событие не закрывает новую сессию. Transport connected / stale RTP / fresh decoded video — разные состояния; frozen last frame не должен выглядеть как live.
8. Pointer move/click/key разрешать только при активной подтверждённой lease, фактическом mode=desktop и валидной геометрии текущего стрима. Unknown mode, camera, stopped/restarting — fail-closed для ввода до согласованного разрешённого состояния. Проверить безопасное отпускание уже нажатых клавиш при teardown; не посылать input в новую/чужую lease.
9. Сохранить непассивный native wheel listener и симметричный removeEventListener. Проверить mount/unmount и смену active; отсутствие overlay/управления не должно блокировать прокрутку страницы. Не возвращать JSX onWheel с preventDefault в passive listener.
10. Типизировать ошибку API и server DTO, избегать новых `any`. Сообщения не содержат PIN/JWT или сырые объекты ошибок. Логировать безопасный reason и generation без спама каждые 5 секунд.

## 3. Проверки

- Выявить фактический frontend test runner. Если покрытия lifecycle нет, добавить минимальную инфраструктуру по стандартам проекта, не считать `npm run build` заменой behavioral tests.
- Матрица fake timers/promises: только viewer; operator desktop; camera; input on/off; unknown mode; duplicate stop/release; late HTTP/WS callback; stopped старого instance; 404/403/409/timeout; unmount/remount; device switch; background tab/network recovery.
- На lost lease — ровно одно уведомление/переход, нет новых HTTP renewal/WS lease renewal старой generation; teardown не затрагивает новый player. На detach input видео сохраняется только если контракт это разрешает.
- Проверить mouse/key не отправляются вне desktop, native wheel без passive warning, баланс listeners после repeated mount.
- Выполнить все релевантные frontend tests и `npm --prefix MenuBuilder/frontend run build` из корня. Если shell находится в frontend, использовать `npm run build`.
- На согласованном стенде: ≥120 с просмотра без движений мыши; отключение ввода; потеря lease; stopped/frozen media отображаются честно. Не утверждать terminal renewal по одному успешному HTTP.

## 4. Handoff

Верни схему UI state/generation, владельца lease и таймеров, таблицу error/event переходов, тесты до/после и сборку. Отдельно перечисли согласования DTO с BFF/app1 и невыполненные browser/E2E проверки. Бандл не доставлять на production без отдельного запроса.