создай промпт, в котором дай указание добавить правило агентам при разработке mqtt-клиента: спрашивать в чате - какой тип клиента создается main_app или extra_service. Если ответ = main_app, то применить в разработке mqtt-клиента дополнительный сценарий:
Client CONNECT:
  will_topic = dev/{SN}/app
  will_payload = app_offline
  will_retain = true

After CONNACK:
  PUBLISH dev/{SN}/app = app_online, retain = true

Normal shutdown:
  PUBLISH dev/{SN}/app = app_offline, retain = true
  DISCONNECT
  --------------
  Если ответ=extra_service, то применить в разработке mqtt-клиента дополнительный сценарий:
Client CONNECT:
  will_topic = dev/{SN}/svc
  will_payload = svc_offline
  will_retain = true

After CONNACK:
  PUBLISH dev/{SN}/svc = svc_online, retain = true

Normal shutdown:
  PUBLISH dev/{SN}/svc = svc_offline, retain = true
  DISCONNECT
  