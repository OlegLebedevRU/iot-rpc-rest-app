цель: сделать скрипт инсталляции mosquitto и конфигурации mocquitto.conf 
scope: скрипт сохранить в D:\Platerra26\tools\mosquitto, для conf целевая папка будет D:\Platerra26\tools\mosquitto, 
конфигурация на основе sn, полученного из leo4proxy. Если sn не получен, то конфиг должен быть нейтральный, не подключаться outbound никуда, бриджа нет. Если sn получен, то создать конфиг по шаблону (предварительно проверь корректность шаблона и используй умную подстановку sn вместо константы сейчас):
````
# Локальный слушатель для внутренних процессов
listener 1883 127.0.0.1
allow_anonymous true

# Настройка Bridge к leo4proxy
connection platerra-upstream
bridge_protocol_version mqttv50
address 127.0.0.1:18883

# Идентификатор терминала для внешнего брокера
remote_clientid a4b0000773c82116d210826

# Отключаем служебные $SYS топики Mosquitto
try_private false
notifications false

# Правила маршрутизации топиков (topic <шаблон> <направление> <QoS> <локальный_префикс> <удаленный_префикс>)
# 1) Все ответы и события терминала наружу:
topic dev/a4b0000773c82116d210826/out out 0
topic dev/a4b0000773c82116d210826/# out 1

# 2) Все входящие серверные команды внутрь:
topic srv/a4b0000773c82116d210826/rsp in 1
topic srv/a4b0000773c82116d210826/# in 1

# Параметры надежности соединения
cleansession true
restart_timeout 5 60
keepalive_interval 60

# Разрешения для основного процесса
user main_app
topic readwrite srv/a4b0000773c82116d210826/#
topic readwrite dev/a4b0000773c82116d210826/#

# Разрешения для сервисного процесса (только отправка)
user extra_service
topic write dev/a4b0000773c82116d210826/evt
persistence false
log_dest file ../../log/mosquitto.log
````
setx /M MOSQUITTO_DIR "D:\Platerra26\tools\mosquitto"
После сохранения шаблона перезапустить службу mosquitto.
cd /d "D:\Platerra26\tools\mosquitto"
mosquitto.exe install
sc.exe start mosquitto
sc.exe query mosquitto