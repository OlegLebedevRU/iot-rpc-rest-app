"""
✅ Особенности реализации
Функция
Реализовано
Использование paho-mqtt
Да, с поддержкой версии 2 API и MQTTv5
Извлечение SN из сертификата
Через OpenSSL.crypto.load_certificate() → get_subject().get_components() → CN
TLS-аутентификация
По клиентскому сертификату и приватному ключу
MQTT 5 User Properties & CorrelationData
Полная поддержка через mqtt.Properties
Асинхронность
На базе asyncio, сетевой цикл MQTT — в отдельном потоке (loop_start)
RPC-потоки
Поддержка Polling и Trigger (через tsk)
События
Отправка evt с кодом 44 (healthcheck)
pip install paho-mqtt pyopenssl
⚠️ pyOpenSSL нужен для парсинга .pem сертификатов.
🔐 Подготовка сертификатов

Убедитесь, что файлы:

cert_0000000.pem — содержит сертификат в формате PEM
key_0000000.pem — содержит приватный ключ (без пароля или с доступом)
CN сертификата должен совпадать с ожидаемым SN
Сертификат должен быть доверенным для брокера
"""

import asyncio
import uuid
import json
import logging
import ssl
from typing import Optional, Dict, Any

import paho.mqtt.client as mqtt
from OpenSSL import crypto

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Константы
BROKER_HOST = "your-mqtt-broker.com"
BROKER_PORT = 8883
CERT_FILE_PATH = "D:/cert_0000000.pem"
KEY_FILE_PATH = "D:/key_0000000.pem"

CA_CERT_PATH = "path/to/ca-cert.pem"  # Опционально, если нужно явно указать CA

# Извлечение SN из сертификата
with open(CERT_FILE_PATH, "rb") as pem_file:
    x509 = crypto.load_certificate(crypto.FILETYPE_PEM, pem_file.read())
cert_components = {
    name.decode(): value.decode("utf-8")
    for name, value in x509.get_subject().get_components()
}
SN = cert_components["CN"]
logger.info(f"Device SN (from certificate CN): {SN}")

# Топики
TOPIC_REQ = f"dev/{SN}/req"
TOPIC_RES = f"dev/{SN}/res"
TOPIC_EVT = f"dev/{SN}/evt"
TOPIC_ACK = f"dev/{SN}/ack"

TOPIC_RSP = f"srv/{SN}/rsp"
TOPIC_TSK = f"srv/{SN}/tsk"
TOPIC_CMT = f"srv/{SN}/cmt"
TOPIC_EVA = f"srv/{SN}/eva"

# Таймеры (в секундах)
REQ_POLL_INTERVAL = 60  # Опрос на наличие задач
HEALTHCHECK_INTERVAL = 300  # Отправка keep-alive


class DeviceClient:
    def __init__(self):
        self.mqttc = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5, client_id=SN
        )

        # Активные корреляции
        self.pending_requests: Dict[str, Dict[str, Any]] = {}

        self._setup_mqtt()

    def _setup_mqtt(self):
        # TLS-аутентификация через сертификат и ключ
        self.mqttc.tls_set(
            ca_certs=CA_CERT_PATH,
            certfile=CERT_FILE_PATH,
            keyfile=KEY_FILE_PATH,
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLSv1_2,
            ciphers=None,
        )

        # Проверка хостнейма
        self.mqttc.tls_insecure_set(False)  # Убедитесь, что сертификат сервера валиден

        # Обработчики событий
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_message = self.on_message
        self.mqttc.on_disconnect = self.on_disconnect

    def start(self):
        logger.info(f"Connecting to broker {BROKER_HOST}:{BROKER_PORT}")
        self.mqttc.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        self.mqttc.loop_start()  # Запуск сетевого цикла в отдельном потоке

        # Подписка после подключения
        self.mqttc.subscribe([(TOPIC_RSP, 1), (TOPIC_TSK, 1), (TOPIC_CMT, 1)])

        # Запуск фоновых задач в asyncio
        loop = asyncio.get_event_loop()
        loop.create_task(self.polling_loop())
        loop.create_task(self.healthcheck_loop())

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            logger.info("Connected to MQTT broker")
        else:
            logger.error(f"Failed to connect to MQTT broker: {reason_code}")

    def on_disconnect(
        self, client, userdata, disconnect_flags, reason_code, properties=None
    ):
        logger.warning(f"Disconnected from MQTT broker: {reason_code}")

    def on_message(self, client, userdata, msg):
        try:
            # Получение свойств MQTT 5
            correlation_data = (
                getattr(msg.properties, "CorrelationData", b"").decode("utf-8")
                if msg.properties
                else ""
            )
            user_props = {}
            if msg.properties and hasattr(msg.properties, "UserProperty"):
                user_props = dict(msg.properties.UserProperty)

            logger.debug(
                "Received message: %s -> %s | Correlation: %s | Props: %s",
                msg.topic,
                msg.payload,
                correlation_data,
                user_props,
            )

            if msg.topic == TOPIC_TSK:
                asyncio.create_task(
                    self.handle_task_announcement(correlation_data, user_props)
                )
            elif msg.topic == TOPIC_RSP:
                asyncio.create_task(
                    self.handle_task_response(correlation_data, msg.payload, user_props)
                )
            elif msg.topic == TOPIC_CMT:
                asyncio.create_task(self.handle_commit(correlation_data, user_props))
            else:
                logger.warning("Unknown topic received: %s", msg.topic)

        except Exception as e:
            logger.error("Error processing message: %s", e)

    async def handle_task_announcement(
        self, correlation_data: str, user_props: Dict[str, str]
    ):
        """Обработка анонса задачи от сервера"""
        method_code = user_props.get("method_code")
        logger.info(
            "Task announced: correlation=%s, method=%s", correlation_data, method_code
        )

        # Подтверждение получения (опционально)
        await self.send_ack(correlation_data)

        # Запрос параметров задачи
        await self.send_request(correlation_data)

    async def handle_task_response(
        self, correlation_data: str, payload: bytes, user_props: Dict[str, str]
    ):
        """Обработка параметров задачи"""
        method_code = user_props.get("method_code")
        if correlation_data in self.pending_requests:
            del self.pending_requests[correlation_data]

        logger.info(
            "Task received: method=%s, correlation=%s", method_code, correlation_data
        )

        # Имитация выполнения задачи
        result = await self.execute_task(method_code, json.loads(payload))

        # Отправка результата
        await self.send_result(correlation_data, result, method_code)

    async def handle_commit(self, correlation_data: str, user_props: Dict[str, str]):
        """Подтверждение получения результата от сервера"""
        result_id = user_props.get("result_id")
        logger.info(
            "Commit received for result_id=%s, correlation=%s",
            result_id,
            correlation_data,
        )

    async def execute_task(self, method_code: str, params: dict) -> dict:
        """Выполнение задачи на устройстве"""
        logger.info("Executing task method_code=%s with params=%s", method_code, params)
        await asyncio.sleep(1)  # имитация работы
        return {"status": "completed", "data": "success"}

    async def send_request(self, correlation_data: Optional[str] = None):
        """Отправка запроса на получение задачи"""
        if not correlation_data:
            correlation_data = (
                "00000000-0000-0000-0000-000000000000"  # Zero UUID для поллинга
            )

        # Создание свойств MQTT 5
        props = mqtt.Properties(mqtt.PacketTypes.PUBLISH)
        props.CorrelationData = correlation_data.encode("utf-8")

        self.mqttc.publish(TOPIC_REQ, "", qos=1, properties=props)
        logger.debug("Sent request with correlation: %s", correlation_data)

        # Сохраняем ожидание ответа
        self.pending_requests[correlation_data] = {
            "type": "request",
            "timestamp": asyncio.get_event_loop().time(),
        }

    async def send_ack(self, correlation_data: str):
        """Отправка подтверждения получения tsk (опционально)"""
        props = mqtt.Properties(mqtt.PacketTypes.PUBLISH)
        props.CorrelationData = correlation_data.encode("utf-8")

        self.mqttc.publish(TOPIC_ACK, "", qos=1, properties=props)
        logger.debug("Sent ACK for correlation: %s", correlation_data)

    async def send_result(self, correlation_data: str, result: dict, method_code: str):
        """Отправка результата выполнения задачи"""
        props = mqtt.Properties(mqtt.PacketTypes.PUBLISH)
        props.CorrelationData = correlation_data.encode("utf-8")
        props.UserProperty = [("status_code", "200"), ("ext_id", "12345")]

        payload = json.dumps(result)
        self.mqttc.publish(TOPIC_RES, payload, qos=1, properties=props)
        logger.info("Result sent for correlation: %s", correlation_data)

    async def send_event(self, event_type_code: int, event_data: dict):
        """Отправка асинхронного события"""
        correlation_id = str(uuid.uuid4())
        props = mqtt.Properties(mqtt.PacketTypes.PUBLISH)
        props.CorrelationData = correlation_id.encode("utf-8")
        props.UserProperty = [
            ("event_type_code", str(event_type_code)),
            ("dev_event_id", "1001"),
            ("dev_timestamp", str(int(asyncio.get_event_loop().time()))),
        ]

        payload = json.dumps(event_data)
        self.mqttc.publish(TOPIC_EVT, payload, qos=1, properties=props)
        logger.info(
            "Event sent: type=%s, correlation=%s", event_type_code, correlation_id
        )

    async def polling_loop(self):
        """Цикл периодического опроса задач"""
        while True:
            try:
                await self.send_request()
            except Exception as e:
                logger.error("Error in polling loop: %s", e)
            await asyncio.sleep(REQ_POLL_INTERVAL)

    async def healthcheck_loop(self):
        """Цикл отправки keep-alive сообщений"""
        while True:
            try:
                await self.send_event(
                    event_type_code=44,
                    event_data={
                        "101": 1047,
                        "102": "2024-08-12T10:31:57Z",
                        "200": 44,
                        "300": [{"310": "1.04.025", "311": 13}],
                    },
                )
            except Exception as e:
                logger.error("Error in healthcheck loop: %s", e)
            await asyncio.sleep(HEALTHCHECK_INTERVAL)


# Точка входа
async def main():
    client = DeviceClient()
    client.start()

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        client.mqttc.loop_stop()
        client.mqttc.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
