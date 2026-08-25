💡 На будущее — краткий чек-лист по CORS в Nginx
Пункт	Как
1. Нельзя * + credentials	Используй точный Origin
2. Избегай дублей add_header	Используй proxy_hide_header
3. OPTIONS → 204	Только заголовки, не проксируй
4. Vary: Origin	Добавь, если динамический Origin
5. Проверяй через curl -H "Origin: http://localhost:5173" -X OPTIONS -v ...	
